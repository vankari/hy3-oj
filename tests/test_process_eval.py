"""process_eval 单测：bug 注入有效性与指标计算。"""
from __future__ import annotations

import random

from hy3_oj.core.schemas import ProcessReview, ReviewStep, StepVerdict
from hy3_oj.eval.process_eval import (
    false_positive_candidates,
    false_positive_rate,
    inject_bug,
    localization_accuracy,
    process_suspects,
)


def test_inject_bug_changes_code() -> None:
    rng = random.Random(42)
    code = "n = int(input())\nfor i in range(n):\n    total += i + 1\nprint(max(total, 0))"
    result = inject_bug(code, rng)
    assert result is not None
    buggy, step, desc = result
    assert buggy != code
    assert isinstance(step, ReviewStep)
    assert desc


def test_inject_bug_no_strategy_returns_none() -> None:
    rng = random.Random(0)
    assert inject_bug("print(42)", rng) is None  # 无可注入模式


def _review(error_step):
    return ProcessReview(
        step_verdicts=[StepVerdict(step=error_step or ReviewStep.COMPREHENSION, passed=error_step is None)],
        error_step=error_step,
    )


def test_localization_accuracy() -> None:
    reviews = [
        (_review(ReviewStep.EDGE_HANDLING), ReviewStep.EDGE_HANDLING),   # 命中
        (_review(ReviewStep.IMPL_CONSISTENCY), ReviewStep.EDGE_HANDLING),  # 未命中
        (_review(ReviewStep.EDGE_HANDLING), ReviewStep.EDGE_HANDLING),   # 命中
    ]
    r = localization_accuracy(reviews)
    assert r["n"] == 3 and r["hit"] == 2
    assert abs(r["accuracy"] - 2 / 3) < 1e-9


def test_false_positive_flow() -> None:
    # v0.5 定罪口径：仅 lucky_pass_flags（机器验证证据）定罪；LLM 语义判定只算存疑
    convicted = ProcessReview(
        step_verdicts=[], lucky_pass_flags=["probe_fail:..."], process_score=0.4
    )
    suspect_only = ProcessReview(
        step_verdicts=[], error_step=ReviewStep.EDGE_HANDLING, process_score=0.5
    )
    clean_review = ProcessReview(step_verdicts=[], process_score=1.0)
    candidates = false_positive_candidates([("p1", convicted), ("p2", suspect_only), ("p3", clean_review)])
    assert len(candidates) == 1 and candidates[0]["problem_id"] == "p1"

    suspects = process_suspects([("p1", convicted), ("p2", suspect_only), ("p3", clean_review)])
    assert len(suspects) == 1 and suspects[0]["problem_id"] == "p2"

    candidates[0]["human_verdict"] = "false_positive"
    r = false_positive_rate(candidates)
    assert r["fp_rate"] == 1.0 and not r["pass"]
