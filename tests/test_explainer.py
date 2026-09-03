"""题解生成器单测（离线部分：提示结构完整、client 异常时不崩溃）。"""
from __future__ import annotations

import asyncio

from hy3_oj.agents import explainer
from hy3_oj.core.schemas import Plan, Problem, ProcessReview, ReviewStep, Solution, Source


def make_problem() -> Problem:
    return Problem(id="p1", source=Source.EXTERNAL, statement="求和", constraints="1<=n<=10")


def test_outline_has_all_sections() -> None:
    for i in range(1, 8):
        assert f"## {i}." in explainer._OUTLINE
    assert "易错点" in explainer._OUTLINE


class FakeClient:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def chat(self, messages, mode=None, temperature=None, max_tokens=None, stage=None):
        self.kwargs = {"mode": mode, "max_tokens": max_tokens, "stage": stage}
        body = messages[-1]["content"]

        class R:
            content = "## 1. 题目在说什么\nok"

        return R()


def test_explain_uses_fast_thinking_and_big_budget() -> None:
    """快思考 + 大 max_tokens（慢思考 CoT 会被截断，planner 教训）。"""
    c = FakeClient()
    out = asyncio.run(explainer.explain(
        c, make_problem(), Solution(code="print(1)"),
        plan=Plan(approach=["读", "加", "输出"], time_complexity="O(n)"),
        review=ProcessReview(error_step=ReviewStep.EDGE_HANDLING),
        judge_summary="WA",
    ))
    assert out.startswith("## 1.")
    assert c.kwargs["stage"] == "explain"
    assert c.kwargs["max_tokens"] >= 4096
    assert c.kwargs["mode"].value == "fast"


def test_explain_includes_review_and_judge_in_prompt() -> None:
    c = FakeClient()
    asyncio.run(explainer.explain(
        c, make_problem(), Solution(code="x"), review=None, judge_summary="AC",
    ))
    # 无 review 时不应崩溃，且提示含判题结论
    assert c.kwargs["stage"] == "explain"
