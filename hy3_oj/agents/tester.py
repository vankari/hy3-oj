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
    """生成 n 个边界测试用例（仅输入；期望输出靠暴力对拍产生）。

    用例必须小规模：暴力参考解也要在这些输入上运行（差分对拍的前提）。
    """
    samples = "\n".join(f"输入：\n{t.input[:200]}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:4000]}\n\n约束：{problem.constraints or '见题面'}\n\n样例输入格式：\n{samples}\n\n"
        f"生成 {n} 个**小规模**边界测试用例的**输入**（严格满足输入约束格式，覆盖：最小规模、"
        "极值、特殊结构；规模要小，O(2^n) 暴力解也能秒过）。输出 JSON 数组：[{\"input\": \"...\"}, ...]，不要输出解释。"
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
        inp = str(it.get("input", "")).strip()
        if inp:  # 基础自校验：非空即收（更严的格式校验可后接正则）
            tests.append(TestCase(input=inp + "\n" if not inp.endswith("\n") else inp,
                                  expected_output=None, is_ai_generated=True))
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
                executor.run_stdout, Solution(code=code), [t.input for t in problem.samples[:3]]
            )
        except Exception as e:  # noqa: BLE001
            log.warning("暴力解验证执行失败 %s: %s", problem.id, e)
            return None
        if outs is None or len(outs) < len(problem.samples[:3]):
            return None
        for t, out in zip(problem.samples[:3], outs):
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
