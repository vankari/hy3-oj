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
_RUNNER = r"""
import subprocess, sys, time, resource, json

code_path, tests_path, time_limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
tests = json.load(open(tests_path))
results = []
for t in tests:
    start = time.monotonic()
    try:
        p = subprocess.run(
            [sys.executable, code_path],
            input=t["input"], capture_output=True, text=True, timeout=time_limit,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        results.append({"stdout": p.stdout, "stderr": p.stderr[-2000:],
                        "exit_code": p.returncode, "timed_out": False, "time_ms": elapsed})
    except subprocess.TimeoutExpired:
        results.append({"stdout": "", "stderr": "TIMEOUT", "exit_code": -1,
                        "timed_out": True, "time_ms": int(time_limit * 1000)})
print("@@RESULTS@@" + json.dumps(results))
"""


class DockerExecutor:
    """一次性容器判题执行器（与 CubeSandbox 适配器同协议）。"""

    def __init__(self, config: dict) -> None:
        sb = config["sandbox"]
        self.image = sb.get("image", "python:3.11-slim")
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

    def execute(self, solution: Solution, tests: list[TestCase]) -> list[JudgeResult]:
        """在单个一次性容器内对全部测试点执行并判题。"""
        if not tests:
            return []
        workdir = Path(tempfile.mkdtemp(prefix=f"hy3oj-{uuid.uuid4().hex[:8]}-")).resolve()
        try:
            (workdir / "main.py").write_text(solution.code, encoding="utf-8")
            (workdir / "runner.py").write_text(_RUNNER, encoding="utf-8")
            import json as _json
            (workdir / "tests.json").write_text(
                _json.dumps([{"input": t.input} for t in tests], ensure_ascii=False), encoding="utf-8"
            )
            raw = self._run_container(workdir)
            return self._to_results(raw, tests)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _run_container(self, workdir: Path) -> list[dict]:
        """起容器跑 runner，解析 @@RESULTS@@ 后的 JSON。"""
        import json as _json

        output = self._client.containers.run(
            image=self.image,
            command=["python", "/work/runner.py", "/work/main.py", "/work/tests.json", str(self.time_limit)],
            volumes={str(workdir): {"bind": "/work", "mode": "ro"}},
            network_disabled=self.network_disabled,
            mem_limit=self.memory,
            nano_cpus=self.nano_cpus,
            detach=False,
            remove=True,
            stdout=True,
            stderr=True,
        ).decode("utf-8", errors="replace")

        marker = "@@RESULTS@@"
        idx = output.rfind(marker)
        if idx == -1:
            # runner 本身崩溃（如容器内 python 异常）：全部按 RE 处理
            return [{"stdout": "", "stderr": output[-2000:], "exit_code": -1, "timed_out": False, "time_ms": 0}]
        return _json.loads(output[idx + len(marker):])

    def _to_results(self, raw: list[dict], tests: list[TestCase]) -> list[JudgeResult]:
        results: list[JudgeResult] = []
        for r, t in zip(raw, tests):
            verdict = classify(exit_code=r["exit_code"], timed_out=r["timed_out"], compile_failed=False)
            diff = ""
            if verdict == Verdict.AC and t.expected_output is not None:
                if not compare_output(t.expected_output, r["stdout"]):
                    verdict = Verdict.WA
                    diff = f"expected: {t.expected_output[:200]!r} got: {r['stdout'][:200]!r}"
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
