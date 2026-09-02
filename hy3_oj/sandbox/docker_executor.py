"""Docker SDK 一次性容器执行器。

安全模型：代码只读挂载进容器；nano_cpus/mem_limit 限资源；network_disabled 断网；
超时强杀；容器用完即删。Windows 宿主机路径经 resolve() 映射容器 POSIX 路径。
与 cube_adapter 同一协议：execute(solution, tests) -> list[JudgeResult]。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

import docker
import docker.errors

from hy3_oj.core.schemas import JudgeResult, Solution, TestCase, Verdict
from hy3_oj.sandbox.judge import classify, compare_output

log = logging.getLogger(__name__)

# 容器内执行脚本：逐个测试点喂 stdin、限时跑、输出以分隔符包裹落盘
# 硬化（177_F1 挂死教训）：进程组整杀（孙进程持有管道也会灭）+ runner 级总预算兜底
_RUNNER = r"""
import subprocess, sys, time, resource, json, os, signal

code_path, tests_path, time_limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
checker = None
if len(sys.argv) > 4 and sys.argv[4] != "-":
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("checker", sys.argv[4])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        checker = mod.check
    except Exception:
        checker = None
tests = json.load(open(tests_path))
results = []
total_budget = max(60.0, time_limit * len(tests) * 3)
t0 = time.monotonic()
for t in tests:
    if time.monotonic() - t0 > total_budget:
        break  # 总预算耗尽：截断，剩余测试点由调用方按缺失处理
    start = time.monotonic()
    p = None
    try:
        p = subprocess.Popen(
            [sys.executable, code_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        out, err = p.communicate(input=t["input"], timeout=time_limit)
        elapsed = int((time.monotonic() - start) * 1000)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)  # 杀整个进程组
        except Exception:
            pass
        out, err, elapsed, timed_out = "", "TIMEOUT", int(time_limit * 1000), True
    checker_ok = None
    if checker is not None and p is not None and p.returncode == 0 and not timed_out:
        try:
            checker_ok = bool(checker(t["input"], out))
        except Exception:
            checker_ok = None
    results.append({"stdout": out, "stderr": err[-2000:],
                    "exit_code": p.returncode if not timed_out else -1,
                    "timed_out": timed_out, "time_ms": elapsed,
                    "checker_ok": checker_ok})
print("@@RESULTS@@" + json.dumps(results))
"""

# 校验器验证脚本：对 (input, output) 对批量跑 check()
_CHECKER_DRIVER = r"""
import sys, json, importlib.util

checker_path, pairs_path = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("checker", checker_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
pairs = json.load(open(pairs_path))
results = []
for inp, out in pairs:
    try:
        results.append(bool(mod.check(inp, out)))
    except Exception:
        results.append(None)
print("@@RESULTS@@" + json.dumps(results))
"""


# C++17 runner：先编译，再逐测试点执行（编译失败 → 全部 CE）
_CPP_RUNNER = r"""
import subprocess, sys, json, time, os, signal

code_path, tests_path, time_limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
tests = json.load(open(tests_path))
results = []

# 1) 编译
try:
    cp = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-pipe", "-static", "-o", "/tmp/main", code_path],
        capture_output=True, text=True, timeout=120,
    )
except subprocess.TimeoutExpired:
    print("@@RESULTS@@" + json.dumps([{"stdout": "", "stderr": "COMPILE TIMEOUT", "exit_code": -1,
                                      "timed_out": False, "time_ms": 0, "compile_failed": True}]))
    sys.exit(0)
if cp.returncode != 0:
    print("@@RESULTS@@" + json.dumps([{"stdout": "", "stderr": cp.stderr[-2000:], "exit_code": cp.returncode,
                                      "timed_out": False, "time_ms": 0, "compile_failed": True}]))
    sys.exit(0)

# 2) 逐测试点执行
total_budget = max(60.0, time_limit * len(tests) * 3)
t0 = time.monotonic()
for t in tests:
    if time.monotonic() - t0 > total_budget:
        break
    start = time.monotonic()
    p = None
    try:
        p = subprocess.Popen(["/tmp/main"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        out, err = p.communicate(input=t["input"], timeout=time_limit)
        elapsed = int((time.monotonic() - start) * 1000)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass
        out, err, elapsed, timed_out = "", "TIMEOUT", int(time_limit * 1000), True
    results.append({"stdout": out, "stderr": err[-2000:],
                    "exit_code": p.returncode if not timed_out else -1,
                    "timed_out": timed_out, "time_ms": elapsed, "compile_failed": False})
while len(results) < len(tests):
    results.append({"stdout": "", "stderr": "runner budget exhausted", "exit_code": -1,
                    "timed_out": False, "time_ms": 0, "compile_failed": False})
print("@@RESULTS@@" + json.dumps(results))
"""


class DockerExecutor:
    """一次性容器判题执行器（与 CubeSandbox 适配器同协议）。

    支持 Python3 与 C++17：按 solution.language 选择镜像与 runner
    （C++17 用于 hard 档 TLE 攻坚——Python 在硬题上性能不足）。
    """

    # 语言 → (镜像, 源码文件名, runner 脚本, 执行命令)
    LANG_PROFILES = {
        "python3": ("python:3.11-slim", "main.py", _RUNNER, ["python", "/work/runner.py"]),
        "cpp17": ("gcc:13", "main.cpp", _CPP_RUNNER, ["python3", "/work/runner.py"]),
    }

    def __init__(self, config: dict) -> None:
        sb = config["sandbox"]
        self.image = sb.get("image", "python:3.11-slim")
        self.cpp_image = sb.get("cpp_image", "gcc:13")
        self.time_limit = float(sb.get("time_limit_s", 5))
        self.memory = f"{int(sb.get('memory_mb', 512))}m"
        self.nano_cpus = int(sb.get("nano_cpus", 1_000_000_000))
        self.network_disabled = bool(sb.get("network_disabled", True))
        self._client = docker.from_env()

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except docker.errors.DockerException:
            return False

    def execute(self, solution: Solution, tests: list[TestCase], checker: str | None = None) -> list[JudgeResult]:
        """在单个一次性容器内对全部测试点执行并判题。

        checker（多解特判，见 special_judge.py）提供时容器内同步执行：
        checker 只能把精确比对的 WA 翻为 AC（接受另一个合法答案），
        精确匹配的 AC 永不被 checker 推翻（误拒绝零风险）。
        """
        if not tests:
            return []
        lang = getattr(solution.language, "value", str(solution.language))
        if lang == "cpp17":
            # C++17 路径：gcc 镜像 + 编译执行（checker 暂不支持，C++ 仅用于 TLE 攻坚）
            workdir = Path(tempfile.mkdtemp(prefix=f"hy3oj-{uuid.uuid4().hex[:8]}-")).resolve()
            try:
                (workdir / "main.cpp").write_text(solution.code, encoding="utf-8")
                (workdir / "runner.py").write_text(_CPP_RUNNER, encoding="utf-8")
                import json as _json
                (workdir / "tests.json").write_text(
                    _json.dumps([{"input": t.input} for t in tests], ensure_ascii=False), encoding="utf-8"
                )
                raw = self._run_container(
                    workdir,
                    ["python3", "/work/runner.py", "/work/main.cpp", "/work/tests.json", str(self.time_limit)],
                    image=self.cpp_image,
                )
                while len(raw) < len(tests):
                    raw.append({"stdout": "", "stderr": "runner budget exhausted", "exit_code": -1,
                                "timed_out": False, "time_ms": 0, "compile_failed": True})
                return self._to_results(raw, tests)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)

        workdir = Path(tempfile.mkdtemp(prefix=f"hy3oj-{uuid.uuid4().hex[:8]}-")).resolve()
        try:
            (workdir / "main.py").write_text(solution.code, encoding="utf-8")
            (workdir / "runner.py").write_text(_RUNNER, encoding="utf-8")
            if checker:
                (workdir / "checker.py").write_text(checker, encoding="utf-8")
            import json as _json
            (workdir / "tests.json").write_text(
                _json.dumps([{"input": t.input} for t in tests], ensure_ascii=False), encoding="utf-8"
            )
            raw = self._run_container(
                workdir,
                ["python", "/work/runner.py", "/work/main.py", "/work/tests.json",
                 str(self.time_limit), "/work/checker.py" if checker else "-"],
            )
            # runner 总预算截断兜底：缺失测试点一律按 RE 计（防"部分通过误判全过"）
            while len(raw) < len(tests):
                raw.append({"stdout": "", "stderr": "runner budget exhausted", "exit_code": -1,
                            "timed_out": False, "time_ms": 0, "checker_ok": None})
            return self._to_results(raw, tests)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def run_checker(self, checker_code: str, pairs: list[tuple[str, str]]) -> list[bool | None] | None:
        """批量跑 check(input, output)（special_judge 反向验证用）；异常返回 None。"""
        if not pairs:
            return []
        workdir = Path(tempfile.mkdtemp(prefix=f"hy3oj-{uuid.uuid4().hex[:8]}-")).resolve()
        try:
            (workdir / "checker.py").write_text(checker_code, encoding="utf-8")
            (workdir / "driver.py").write_text(_CHECKER_DRIVER, encoding="utf-8")
            import json as _json
            (workdir / "pairs.json").write_text(_json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
            output = self._run_container_raw(
                workdir, ["python", "/work/driver.py", "/work/checker.py", "/work/pairs.json"]
            )
            marker = "@@RESULTS@@"
            idx = output.rfind(marker)
            if idx == -1:
                return None
            return _json.loads(output[idx + len(marker):])
        except (docker.errors.DockerException, _json.JSONDecodeError):
            return None
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def run_stdout(self, solution: Solution, inputs: list[str]) -> list[str]:
        """只执行不判题：返回每个输入对应的 stdout（行为探针用，见 agents/prober.py）。"""
        if not inputs:
            return []
        workdir = Path(tempfile.mkdtemp(prefix=f"hy3oj-{uuid.uuid4().hex[:8]}-")).resolve()
        try:
            (workdir / "main.py").write_text(solution.code, encoding="utf-8")
            (workdir / "runner.py").write_text(_RUNNER, encoding="utf-8")
            import json as _json
            (workdir / "tests.json").write_text(
                _json.dumps([{"input": i} for i in inputs], ensure_ascii=False), encoding="utf-8"
            )
            raw = self._run_container(
                workdir,
                ["python", "/work/runner.py", "/work/main.py", "/work/tests.json",
                 str(self.time_limit), "-"],
            )
            return [r["stdout"] for r in raw]
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _run_container_raw(self, workdir: Path, command: list[str], image: str | None = None) -> str:
        """起容器执行命令，返回原始输出（stdout+stderr 合并）。

        容器内 runner 整体崩溃（如候选代码 segfault 杀崩 runner，exit 139）时
        不让 ContainerError 中断整批评测，按"无结果"返回由上层归类 RE。
        """
        try:
            return self._client.containers.run(
                image=image or self.image,
                command=command,
                volumes={str(workdir): {"bind": "/work", "mode": "ro"}},
                network_disabled=self.network_disabled,
                mem_limit=self.memory,
                nano_cpus=self.nano_cpus,
                detach=False,
                remove=True,
                stdout=True,
                stderr=True,
            ).decode("utf-8", errors="replace")
        except docker.errors.ContainerError as e:
            log.warning("容器非零退出（按 runner 崩溃处理）: exit=%s", e.exit_status)
            return f"CONTAINER_CRASH exit={e.exit_status}"

    def _run_container(self, workdir: Path, command: list[str], image: str | None = None) -> list[dict]:
        """起容器跑 runner，解析 @@RESULTS@@ 后的 JSON。"""
        import json as _json

        output = self._run_container_raw(workdir, command, image=image)
        marker = "@@RESULTS@@"
        idx = output.rfind(marker)
        if idx == -1:
            # runner 本身崩溃（如容器内 python 异常）：全部按 RE 处理
            return [{"stdout": "", "stderr": output[-2000:], "exit_code": -1, "timed_out": False,
                     "time_ms": 0, "checker_ok": None, "compile_failed": False}]
        return _json.loads(output[idx + len(marker):])

    def _to_results(self, raw: list[dict], tests: list[TestCase]) -> list[JudgeResult]:
        results: list[JudgeResult] = []
        for r, t in zip(raw, tests):
            verdict = classify(exit_code=r["exit_code"], timed_out=r["timed_out"],
                               compile_failed=bool(r.get("compile_failed")))
            diff = ""
            if verdict == Verdict.AC:
                if t.expected_output is not None:
                    exact = compare_output(t.expected_output, r["stdout"])
                    # 特判语义：checker 只能把 WA 翻 AC；精确匹配的 AC 永不被推翻
                    if not exact and r.get("checker_ok") is not True:
                        verdict = Verdict.WA
                        diff = f"expected: {t.expected_output[:200]!r} got: {r['stdout'][:200]!r}"
                elif r.get("checker_ok") is False:
                    # 无标答测试点（AI 生成）上的特判：checker 拒绝才算 WA
                    verdict = Verdict.WA
                    diff = f"checker rejected: got {r['stdout'][:200]!r}"
            results.append(
                JudgeResult(
                    verdict=verdict,
                    failed_test=t if verdict != Verdict.AC else None,
                    stderr=r["stderr"],
                    time_ms=r["time_ms"],
                    diff_excerpt=diff,
                )
            )
        return results

    def close(self) -> None:
        self._client.close()
