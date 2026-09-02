"""多解特判单测（fake client/executor；Docker 端到端用例在 test_sandbox_smoke）。"""
from __future__ import annotations

from hy3_oj.core.schemas import Problem, Source, TestCase
from hy3_oj.sandbox import special_judge


def make_problem(statement: str, with_ref: bool = True) -> Problem:
    return Problem(
        id="px", source=Source.CODECONTESTS, statement=statement,
        samples=[TestCase(input="2\n0 1\n1 0\n", expected_output="1 2\n")],
        reference_solutions=["REF"] if with_ref else [],
    )


def test_needs_special_judge_detects_multi_answer() -> None:
    assert special_judge.needs_special_judge(make_problem(
        "If there are multiple possible solutions, print any of them."
    ))
    assert special_judge.needs_special_judge(make_problem("Print any valid answer."))


def test_needs_special_judge_ignores_unique_answer() -> None:
    assert not special_judge.needs_special_judge(make_problem(
        "Print the single integer — the minimal possible number of stones."
    ))


class FakeExecutor:
    """预置参考解输出与 checker 判定结果。"""

    def __init__(self, ref_outs: list[str], checker_verdicts: list[bool | None]):
        self.ref_outs = ref_outs
        self.checker_verdicts = checker_verdicts

    def run_stdout(self, code, inputs):  # noqa: ARG002
        return self.ref_outs

    def run_checker(self, checker_code, pairs):  # noqa: ARG002
        return self.checker_verdicts


def test_validate_checker_accepts_trustworthy() -> None:
    # 参考解输出全接受 + 空输出拒绝 → 可信
    ex = FakeExecutor(["1 2\n"], [True, False])
    ok, _ = special_judge.validate_checker(ex, make_problem("print any of them"), "def check(i,o): ...")
    assert ok


def test_validate_checker_rejects_always_true() -> None:
    # 空输出也接受（恒真 checker）→ 不可信
    ex = FakeExecutor(["1 2\n"], [True, True])
    ok, detail = special_judge.validate_checker(ex, make_problem("print any of them"), "def check(i,o): ...")
    assert not ok and "恒真" in detail


def test_validate_checker_rejects_reference_rejecting() -> None:
    # 连官方参考解的输出都拒绝 → checker 本身错
    ex = FakeExecutor(["1 2\n"], [False, False])
    ok, detail = special_judge.validate_checker(ex, make_problem("print any of them"), "def check(i,o): ...")
    assert not ok and "被拒绝" in detail


def test_extract_code_requires_check_function() -> None:
    assert special_judge._extract_code("```python\ndef check(i, o):\n    return True\n```")
    assert not special_judge._extract_code("```python\ndef solve():\n    pass\n```")
