"""数据契约单测：模型可构造、可序列化回放、枚举取值完整。"""
from __future__ import annotations

from hy3_oj.core.schemas import (
    JudgeResult,
    Plan,
    Problem,
    ProcessErrorType,
    ProcessReview,
    ReviewStep,
    Solution,
    Source,
    StepVerdict,
    TestCase,
    Verdict,
)


def make_problem() -> Problem:
    return Problem(
        id="cc-1",
        source=Source.CODECONTESTS,
        statement="给定 n 个整数，求和。",
        samples=[TestCase(input="3\n1 2 3\n", expected_output="6")],
        difficulty="easy",
        tags=["brute_force"],
    )


def test_problem_roundtrip() -> None:
    p = make_problem()
    restored = Problem.model_validate_json(p.model_dump_json())
    assert restored == p


def test_pipeline_models() -> None:
    p = make_problem()
    plan = Plan(algorithm_tags=["brute_force"], approach=["读入", "求和", "输出"], time_complexity="O(n)")
    sol = Solution(code="print(sum(mapint, input().split())))", plan_ref="v1")
    jr = JudgeResult(verdict=Verdict.WA, failed_test=p.samples[0], diff_excerpt="expected 6, got 0")
    assert plan.time_complexity == "O(n)"
    assert jr.verdict == Verdict.WA


def test_process_review_defaults() -> None:
    review = ProcessReview(
        step_verdicts=[StepVerdict(step=ReviewStep.COMPREHENSION, passed=False, evidence="漏看约束")],
        error_step=ReviewStep.COMPREHENSION,
        error_type=ProcessErrorType.MISREAD,
        process_score=0.2,
    )
    assert review.error_step == ReviewStep.COMPREHENSION
    assert len(ReviewStep) == 5  # 五段式审查粒度
    assert len(ProcessErrorType) == 8  # 过程层错误分类体系
