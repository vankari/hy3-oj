"""行为探针（R6 蒙对检测的机器验证层，v0.5 新增）。

动机：单遍 LLM 审查在 AC 解上精度/召回不可兼得（v0.3 误报 93%、v0.4 漏真实缺陷）。
对"恰好通过弱测试但实现有缺陷"的样本，改用确定性行为验证：

1. 从题面文本抽取官方样例 I/O 对（LLM 抽取，按题缓存）；
2. 用官方参考解反向校验探针：参考解也过不了的"样例"是抽取噪音，丢弃（近零误报）；
3. 被审代码在探针上失败而参考解通过 → 行为级蒙对铁证（如 p01811 官方样例
   AABCC→Yes 被 AC 解输出 No，CodeContests 测试弱未覆盖）。

探针失败是"过程不成立"的确定性证据，process_score 封顶 0.4。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from hy3_oj.core.schemas import GenMode, Problem, Solution, TestCase
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor
from hy3_oj.sandbox.judge import compare_output

log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)
_CACHE_DIR = Path("runs/statement_samples")


def _cache_path(problem_id: str) -> Path:
    safe = re.sub(r"[^\w\-.]+", "_", problem_id)
    return _CACHE_DIR / f"{safe}.json"


async def extract_statement_samples(
    client: Hy3Client, problem: Problem, use_cache: bool = True
) -> list[TestCase]:
    """从题面文本抽取官方样例 I/O 对（LLM 快思考，按题缓存落盘）。"""
    if use_cache and _cache_path(problem.id).exists():
        try:
            return [TestCase(**t) for t in json.loads(_cache_path(problem.id).read_text(encoding="utf-8"))]
        except (json.JSONDecodeError, TypeError):
            pass

    user = (
        "从下面的竞赛题面中抽取全部**官方样例**的输入与预期输出，逐字照抄。"
        "注意：忽略解释性文字（Note/Explanation）；输入输出保持原始换行与空格；"
        "题面可能含 HTML 转义（&lt; 即 <）。输出 JSON 数组："
        '[{"input": "...", "output": "..."}, ...]，没有样例则输出 []。\n\n'
        f"题面：\n{problem.statement[:8000]}"
    )
    tests: list[TestCase] = []
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是数据标注员，只输出 JSON 数组。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.0, max_tokens=4096, stage="probe_extract",
        )
        m = _JSON_RE.search(r.content)
        items = json.loads(m.group(0)) if m else []
        for it in items:
            inp, out = str(it.get("input", "")), str(it.get("output", ""))
            if inp.strip() and out.strip():
                tests.append(TestCase(input=inp if inp.endswith("\n") else inp + "\n",
                                      expected_output=out))
    except Exception as e:  # noqa: BLE001
        log.warning("样例抽取失败 %s: %s", problem.id, e)
        return []

    if use_cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(problem.id).write_text(
            json.dumps([t.model_dump() for t in tests], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return tests


def _run_stdout(executor: DockerExecutor, code: str, inputs: list[str]) -> list[str] | None:
    """跑代码取 stdout（复用执行器容器机制）；执行异常返回 None。"""
    try:
        return executor.run_stdout(Solution(code=code), inputs)
    except Exception as e:  # noqa: BLE001
        log.warning("探针执行异常: %s", e)
        return None


async def probe(
    client: Hy3Client,
    executor: DockerExecutor,
    problem: Problem,
    solution: Solution,
    max_probes: int = 4,
) -> list[str]:
    """行为探针主流程：返回命中的蒙对证据（空 = 未发现）。

    探针可信条件：官方参考解在同输入上的输出与抽取的预期输出一致（比对通过）。
    命中条件：被审代码在同输入上的输出与预期输出不一致。
    """
    if not problem.reference_solutions:
        return []  # 无参考解无法反向校验探针，宁缺毋滥（FP 防线）

    probes = (await extract_statement_samples(client, problem))[:max_probes]
    if not probes:
        return []

    inputs = [t.input for t in probes]
    ref_outs = await __run_async(executor, problem.reference_solutions[0], inputs)
    cand_outs = await __run_async(executor, solution.code, inputs)
    if ref_outs is None or cand_outs is None:
        return []

    flags: list[str] = []
    for t, ref_out, cand_out in zip(probes, ref_outs, cand_outs):
        expected = t.expected_output or ""
        if not compare_output(expected, ref_out):
            continue  # 探针本身不可信（抽取噪音/题面样例与判题口径不同），丢弃
        if not compare_output(expected, cand_out):
            flags.append(
                f"probe_fail:input={t.input[:60]!r},expected={expected[:60]!r},"
                f"got={cand_out[:60]!r}（官方参考解通过，被审代码失败）"
            )
    return flags


async def __run_async(executor: DockerExecutor, code: str, inputs: list[str]) -> list[str] | None:
    import asyncio

    return await asyncio.to_thread(_run_stdout, executor, code, inputs)
