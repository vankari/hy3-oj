"""Coder：K 路温度分层采样生成代码（AlphaCodium 两阶段：先要点复述再写码）。"""
from __future__ import annotations

import re

from hy3_oj.core.schemas import GenMode, Plan, Problem, Solution
from hy3_oj.llm.client import Hy3Client

_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """从模型输出提取 ```python 代码块；无代码块时回退为全文（尽力而为）。"""
    m = _CODE_RE.search(text)
    return (m.group(1) if m else text).strip()


def build_messages(problem: Problem, plan: Plan | None = None) -> list[dict[str, str]]:
    """组装 Coder 提示（要点化 plan 可选；基线直出时 plan=None）。"""
    samples = "\n".join(
        f"输入：\n{t.input}\n输出：\n{t.expected_output or ''}" for t in problem.samples[:2]
    )
    plan_text = ""
    if plan and plan.approach:
        plan_text = "解题计划：\n" + "\n".join(f"- {s}" for s in plan.approach) + "\n\n"
    user = (
        f"{plan_text}题目：\n{problem.statement}\n\n样例：\n{samples}\n\n"
        "先复述要点化解法（不超过 5 条），然后输出完整 Python3 代码"
        "（```python 代码块，仅标准库，stdin 读入/stdout 输出）。"
    )
    return [
        {"role": "system", "content": "你是竞赛选手。严格按约束实现，不输出调试信息。"},
        {"role": "user", "content": user},
    ]


async def generate(
    client: Hy3Client,
    problem: Problem,
    plan: Plan | None = None,
    k: int = 1,
    temperatures: list[float] | None = None,
    mode: GenMode = GenMode.FAST,
) -> list[Solution]:
    """K 路采样：逐路调用（缓存使重复调用零成本），提取代码块为 Solution。"""
    temps = (temperatures or [0.2])[:k] or [0.2]
    messages = build_messages(problem, plan)
    solutions: list[Solution] = []
    for i in range(k):
        r = await client.chat(messages, mode=mode, temperature=temps[i % len(temps)], stage="code")
        solutions.append(
            Solution(code=extract_code(r.content), plan_ref="inline" if plan else None,
                     temperature=temps[i % len(temps)], gen_mode=mode)
        )
    return solutions
