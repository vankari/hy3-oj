"""Reviewer：过程评估器（骨架，任务书核心 R3–R6）。

输入完整解题轨迹 → 输出 ProcessReview。对 AC 与失败样本都运行。

五段式分步审查（错误步骤定位 = 首个 fail 段）：
①题意理解 ②算法选型 ③复杂度论证 ④边界处理 ⑤实现一致性

蒙对检测（规则先行，LLM 复核）：
1. 硬编码样例字面量；2. 输入特判分支；3. 声称复杂度 vs 实际实现不符；
4. 大数溢出/精度巧合（多语言阶段启用）。

TODO(D9): 实现 review(trace) -> ProcessReview；
蒙对规则见 check_lucky_pass(code, samples, plan)。
"""
from __future__ import annotations

import re

from hy3_oj.core.schemas import Plan, Problem, Solution


def check_hardcoded_samples(solution: Solution, problem: Problem) -> list[str]:
    """规则 1：代码中出现样例输入/输出字面量（占位实现，供单测）。"""
    flags: list[str] = []
    for sample in problem.samples:
        for literal in {sample.input.strip(), (sample.expected_output or "").strip()} - {""}:
            if len(literal) >= 4 and literal in solution.code:
                flags.append(f"hardcoded_sample:{literal[:32]}")
    return flags


def check_input_special_case(solution: Solution) -> list[str]:
    """规则 2：输入特判分支，如 `if n == 5: print(...)`（占位实现）。"""
    pattern = re.compile(r"if\s+\w+\s*==\s*\d+\s*:\s*print", re.MULTILINE)
    return [f"special_case:{m.group(0)[:48]}" for m in pattern.finditer(solution.code)]


def check_complexity_mismatch(solution: Solution, plan: Plan) -> list[str]:
    """规则 3：Plan 声称复杂度 vs 实现嵌套循环深度不符（启发式占位）。"""
    # TODO(D9): 解析 plan.time_complexity 与 AST 循环嵌套深度比对
    return []
