"""Reviewer 蒙对检测规则单测（不依赖 LLM）。

v0.3：全部静态规则只产出候选信号（lucky_pass_signals），定罪一律靠 LLM 复核；
纯规则降级模式（client=None）不定罪、不封顶。
"""
from __future__ import annotations

import asyncio

from hy3_oj.agents.reviewer import (
    _confirm_signals,
    _max_effective_loop_depth,
    complexity_signals,
    hardcoded_sample_signals,
    lucky_pass_signals,
    review,
    special_case_signals,
)
from hy3_oj.core.schemas import Plan, Problem, Solution, Source, TestCase


def make_problem() -> Problem:
    return Problem(
        id="t1",
        source=Source.CODECONTESTS,
        statement="求和",
        samples=[TestCase(input="3\n1 2 3\n", expected_output="1000000007\n")],
    )


def test_hardcoded_sample_signal() -> None:
    # 样例字面量出现在代码中 → 产生信号（是否定罪由 LLM 判）
    sol = Solution(code='data = "3\\n1 2 3"\nprint(1000000007)')
    assert hardcoded_sample_signals(sol, make_problem())


def test_output_vocabulary_also_signals_but_not_convicted() -> None:
    # 输出词汇（如 First/Second）同样产生信号——v0.2 硬规则因此误报；
    # v0.3 只出信号，需 _confirm_signals 确认
    problem = Problem(
        id="t2", source=Source.CODECONTESTS, statement="博弈",
        samples=[TestCase(input="5\n", expected_output="First\n")],
    )
    sol = Solution(code="n=int(input())\nprint('First' if n%2 else 'Second')")
    signals = hardcoded_sample_signals(sol, problem)
    assert signals  # 信号在（召回）
    # LLM 未确认（如回复中 rejected）→ 不定罪
    data = {"flag_verdicts": [{"signal": signals[0], "confirmed": False, "reason": "输出词汇"}]}
    assert _confirm_signals(data, signals) == []


def test_special_case_signal() -> None:
    sol = Solution(code="n=int(input())\nif n == 5: print(42)\nelse: print(0)")
    assert special_case_signals(sol)


def test_lucky_pass_signals_aggregates_all_types() -> None:
    plan = Plan(time_complexity="O(n)", approach=["扫一遍"])
    sol = Solution(
        code='if n == 5: print(1000000007)\n'
        "for i in range(n):\n    for j in range(n):\n        for k in range(n):\n            pass"
    )
    signals = lucky_pass_signals(sol, make_problem(), plan)
    kinds = {s.split(":")[0] for s in signals}
    assert kinds == {"hardcoded_sample", "special_case", "complexity_suspect"}


# ---------- AST 有效嵌套循环深度 ----------

def test_effective_depth_counts_nesting() -> None:
    code = "for i in range(n):\n    for j in range(n):\n        for k in range(n):\n            pass"
    assert _max_effective_loop_depth(code) == 3


def test_effective_depth_ignores_sequential_loops() -> None:
    # 顺序循环不是嵌套（v0.1 按行缩进的误判来源之一）
    code = "for i in range(n):\n    pass\nfor j in range(n):\n    pass"
    assert _max_effective_loop_depth(code) == 1


def test_effective_depth_ignores_small_constant_bounds() -> None:
    # range(3)/range(4) 是常数因子，不计入有效深度（1149_B 误报场景）
    code = (
        "for i in range(n):\n"
        "    for a in range(3):\n"
        "        for b in range(4):\n"
        "            for c in range(3):\n"
        "                pass"
    )
    assert _max_effective_loop_depth(code) == 1


def test_effective_depth_syntax_error() -> None:
    assert _max_effective_loop_depth("def broken(:\n") == 0


# ---------- 复杂度信号 ----------

def test_complexity_signal_fires_on_deep_nesting() -> None:
    plan = Plan(time_complexity="O(n)", approach=["扫一遍"])
    deep = Solution(code="for i in range(n):\n    for j in range(n):\n        for k in range(n):\n            pass")
    assert complexity_signals(deep, plan)


def test_complexity_signal_silent_for_constant_inner_loops() -> None:
    # 1250_B 误报场景：嵌套虽深但内层是常数界，且量级可过 → 不出信号
    plan = Plan(time_complexity="O(n)", approach=["扫一遍"])
    ok = Solution(code="for i in range(n):\n    for a in range(3):\n        for b in range(3):\n            pass")
    assert not complexity_signals(ok, plan)


def test_complexity_signal_silent_without_plan() -> None:
    deep = Solution(code="for i in range(n):\n    for j in range(n):\n        for k in range(n):\n            pass")
    assert not complexity_signals(deep, None)


# ---------- 信号确认逻辑 ----------

def test_confirm_signals_requires_explicit_true() -> None:
    signals = ["sig_a", "sig_b", "sig_c"]
    data = {"flag_verdicts": [
        {"signal": "sig_a", "confirmed": True, "reason": "确实蒙对"},
        {"signal": "sig_b", "confirmed": False, "reason": "合法"},
        # sig_c 未回应 → 默认不定罪（宁缺毋滥）
    ]}
    confirmed = _confirm_signals(data, signals)
    assert len(confirmed) == 1 and "sig_a" in confirmed[0]


# ---------- 纯规则降级模式（v0.3：不定罪） ----------

def test_review_rules_only_never_convicts() -> None:
    problem = make_problem()
    cheater = Solution(code='if n == 5: print(42)\nprint("3\\n1 2 3")')
    result = asyncio.run(review(None, problem, None, cheater, "AC"))
    assert not result.lucky_pass_flags   # 降级模式不定罪
    assert result.process_score == 1.0
    assert "静态信号" in result.step_verdicts[0].evidence  # 信号留痕

    clean = Solution(code="print(sum(map(int, input().split())))")
    ok = asyncio.run(review(None, problem, None, clean, "AC"))
    assert not ok.lucky_pass_flags
    assert ok.process_score == 1.0
