"""Tester：边界测试用例生成 + 暴力对拍 oracle（快思考，CodeContests+ 思路）。

- gen_tests：生成小规模边界输入（暴力解可承受），非空自校验入库；
- gen_brute_force：生成"显然正确"的暴力参考解，先在样例上验证可信；
- differential：候选解 vs 暴力解在 AI 用例上差分比对，拦截"过样例但错边界"的提交。
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
_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_BRUTE_CACHE = Path("runs/brute")


def _extract_list(text: str) -> list:
    m = _JSON_RE.search(text)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return []


async def gen_tests(client: Hy3Client, problem: Problem, n: int = 5) -> list[TestCase]:
    """生成 n 个**边界**测试用例（仅输入；期望输出不预填，判题走暴力差分对拍）。

    只生成最小规模/极值/特殊结构等边界输入（小规模，暴力解也能跑），
    普通随机覆盖用例请交给 gen_bf_tests（用暴力解生成标答）。
    """
    samples = "\n".join(f"输入：\n{t.input[:200]}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:4000]}\n\n约束：{problem.constraints or '见题面'}\n\n样例输入格式：\n{samples}\n\n"
        f"生成 {n} 个**小规模边界**测试用例的**输入**（严格满足输入约束格式，覆盖：最小规模、"
        "极值、特殊结构、退化/空等边界情况；规模要小，O(2^n) 暴力解也能秒过）。"
        "注意：只生成边界/极值/特殊结构类输入，不要生成普通随机覆盖用例。"
        "输出 JSON 数组：[{\"input\": \"...\"}, ...]，不要输出解释。"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是竞赛出题人，只输出 JSON 数组。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.3, max_tokens=4096, stage="test_gen",
        )
        items = _extract_list(r.content)
    except Exception:  # noqa: BLE001
        return []

    tests = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("input"), str):
            continue
        inp = it["input"].strip()
        if inp:  # 基础自校验：非空即收（更严的格式校验可后接正则）
            tests.append(TestCase(input=inp + "\n" if not inp.endswith("\n") else inp,
                                  expected_output=None, is_ai_generated=True,
                                  is_boundary=True))  # 边界用例：判题走差分对拍，不预填标答
    return tests[:n]


async def gen_bf_tests(
    client: Hy3Client, problem: Problem, executor: DockerExecutor, brute_code: str, n: int = 8
) -> list[TestCase]:
    """生成 n 个**非边界**普通测试用例，并用暴力解（bf oracle）跑出 expected_output 填标答。

    这些用例判题时走标准输出对比，标答由暴力解保证正确性，杜绝"无标答放水"。
    自校验：暴力解必须在 time_limit 内产出非空输出，否则该用例不可靠、丢弃不入库。
    """
    samples = "\n".join(f"输入：\n{t.input[:200]}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:4000]}\n\n约束：{problem.constraints or '见题面'}\n\n样例输入格式：\n{samples}\n\n"
        f"生成 {n} 个**小规模、非边界**的随机/覆盖性测试用例输入（严格满足输入格式，"
        "规模适中、O(n^2) 内可解、覆盖多种普通数据结构与流程，不要极值或特殊退化结构）。"
        "输出 JSON 数组：[{\"input\": \"...\"}, ...]，不要输出解释。"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是竞赛出题人，只输出 JSON 数组。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.4, max_tokens=4096, stage="test_gen_bf",
        )
        items = _extract_list(r.content)
    except Exception:  # noqa: BLE001
        return []

    inputs = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("input"), str):
            continue
        inp = it["input"].strip()
        if inp:
            inputs.append(inp + "\n" if not inp.endswith("\n") else inp)
    if not inputs:
        return []

    # 用暴力解跑出标答（bf 即 oracle，保证判题正确性）
    import asyncio

    try:
        outs = await asyncio.to_thread(executor.run_stdout, Solution(code=brute_code), inputs)
    except Exception as e:  # noqa: BLE001
        log.warning("bf 跑测试输入失败 %s: %s", problem.id, e)
        return []
    if outs is None or len(outs) < len(inputs):
        return []

    tests = []
    for inp, out in zip(inputs, outs):
        if out is None or out.strip() == "":
            continue  # bf 无输出：不可靠，丢弃
        tests.append(TestCase(
            input=inp,
            expected_output=out if out.endswith("\n") else out + "\n",
            is_ai_generated=True,
            is_boundary=False,  # 普通用例：标答由 bf 生成，走标准对比
        ))
    return tests[:n]


async def gen_brute_force(
    client: Hy3Client, problem: Problem, executor: DockerExecutor, use_cache: bool = True
) -> str | None:
    """生成暴力参考解并用题面样例验证可信（样例全对才可用作差分 oracle）。

    快思考：代码属结构化输出，慢思考会被 CoT 截断（planner 同根因）。
    """
    safe = re.sub(r"[^\w\-.]+", "_", problem.id)
    cache = _BRUTE_CACHE / f"{safe}.py"
    if use_cache and cache.exists():
        return cache.read_text(encoding="utf-8")

    samples = "\n---\n".join(
        f"输入：\n{t.input[:300]}\n预期输出：\n{(t.expected_output or '')[:300]}"
        for t in problem.samples[:3]
    )
    user = (
        "为以下竞赛题写一个**暴力解法**（stdin/stdout 完整程序）："
        "正确性显然、允许指数级复杂度（只会在小规模输入上运行）。"
        "不要用任何优化技巧，优先可读的正确性。只输出代码。\n\n"
        f"题目：\n{problem.statement[:5000]}\n\n样例：\n{samples}"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是竞赛选手，只输出 Python 代码。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.0, max_tokens=4096, stage="brute_gen",
        )
        m = _CODE_RE.search(r.content)
        code = m.group(1) if m else r.content
    except Exception as e:  # noqa: BLE001
        log.warning("暴力解生成失败 %s: %s", problem.id, e)
        return None

    # 样例验证：暴力解必须在全部样例上输出正确，否则不可信
    import asyncio

    if problem.samples:
        try:
            outs = await asyncio.to_thread(
                executor.run_stdout, Solution(code=code), [t.input for t in problem.samples]
            )
        except Exception as e:  # noqa: BLE001
            log.warning("暴力解验证执行失败 %s: %s", problem.id, e)
            return None
        if outs is None or len(outs) < len(problem.samples):
            return None
        for t, out in zip(problem.samples, outs):
            if not compare_output(t.expected_output or "", out):
                log.info("暴力解样例验证未过，弃用: %s", problem.id)
                return None

    _BRUTE_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(code, encoding="utf-8")
    return code


def differential_mismatches(
    executor: DockerExecutor, candidate_code: str, brute_code: str, inputs: list[str]
) -> list[dict]:
    """差分对拍：候选解与暴力解在同一批输入上的输出不一致清单。"""
    if not inputs:
        return []
    cand = executor.run_stdout(Solution(code=candidate_code), inputs)
    brute = executor.run_stdout(Solution(code=brute_code), inputs)
    if cand is None or brute is None:
        return []
    mismatches = []
    for inp, c, b in zip(inputs, cand, brute):
        if not compare_output(b, c):
            # c/b 可能为 None（执行失败/超时）：compare_output 判不一致，
            # 但记录时不能再切片，否则 TypeError（生产踩过）
            mismatches.append({
                "input": inp[:120],
                "candidate": (c or "")[:120],
                "brute": (b or "")[:120],
                "no_output": c is None or b is None,  # 标记：无输出（不可作为"答案错误"证据）
            })
    return mismatches
