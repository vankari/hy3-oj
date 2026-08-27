"""Reviewer 蒙对检测规则单测（不依赖 LLM）。"""
from __future__ import annotations

import asyncio

from hy3_oj.agents.reviewer import (
    check_complexity_mismatch,
    check_hardcoded_samples,
    check_input_special_case,
    lucky_pass_flags,
    review,
)
from hy3_oj.core.schemas import Plan, Problem, Solution, Source, TestCase


def make_problem() -> Problem:
    return Problem(
        id="t1",
        source=Source.CODECONTESTS,
        statement="求和",
        samples=[TestCase(input="3\n1 2 3\n", expected_output="1000000007\n")],
    )


def test_hardcoded_sample_detected() -> None:
    # 样例输入与输出字面量同时出现在代码中 → 蒙对铁证
    sol = Solution(code='data = "3\\n1 2 3"\nprint(1000000007)')
    assert check_hardcoded_samples(sol, make_problem())


def test_hardcoded_sample_clean() -> None:
    sol = Solution(code="n=int(input()); print(sum(map(int,input().split())))")
    assert not check_hardcoded_samples(sol, make_problem())


def test_special_case_detected() -> None:
    sol = Solution(code="n=int(input())\nif n == 5: print(42)\nelse: print(0)")
    assert check_input_special_case(sol)


def test_complexity_mismatch() -> None:
    plan = Plan(time_complexity="O(n)", approach=["扫一遍"])
    bad = Solution(code="for i in x:\n    for j in y:\n        for k in z:\n            pass")
    good = Solution(code="for i in x:\n    pass")
    assert check_complexity_mismatch(bad, plan)
    assert not check_complexity_mismatch(good, plan)


def test_review_rules_only() -> None:
    problem = make_problem()
    cheater = Solution(code='if n == 5: print(42)\nprint("1 2 3")')
    result = asyncio.run(review(None, problem, None, cheater, "AC"))
    assert result.lucky_pass_flags
    assert result.process_score <= 0.4

    clean = Solution(code="print(sum(map(int, input().split())))")
    ok = asyncio.run(review(None, problem, None, clean, "AC"))
    assert not ok.lucky_pass_flags
    assert ok.process_score == 1.0
