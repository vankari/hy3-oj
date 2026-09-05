"""快慢思考调度策略单测（重点技术 1：成本-效果帕累托）。"""
from __future__ import annotations

import pytest

from hy3_oj.core.schemas import GenMode
from hy3_oj.llm.router import route


def test_slow_stages_always_slow() -> None:
    """规划/归因/过程审查固定走慢思考（推理质量优先）。"""
    for stage in ("plan", "reflect", "review"):
        assert route(stage) == GenMode.SLOW, stage


def test_fast_stages_default_fast() -> None:
    """生成/解析等默认快思考（成本优先）。"""
    assert route("code") == GenMode.FAST
    assert route("parse") == GenMode.FAST


def test_difficulty_upgrade() -> None:
    """hard 档升格慢思考。"""
    assert route("code", difficulty="hard") == GenMode.SLOW
    assert route("code", difficulty="easy") == GenMode.FAST


def test_fail_rounds_upgrade() -> None:
    """连续失败 ≥2 轮升格慢思考。"""
    assert route("code", fail_rounds=1) == GenMode.FAST
    assert route("code", fail_rounds=2) == GenMode.SLOW
    assert route("code", fail_rounds=5) == GenMode.SLOW


def test_budget_exhausted_forces_fast() -> None:
    """预算耗尽时强制快思考（成本控制兜底）。"""
    assert route("plan", budget_left=0) == GenMode.FAST
    assert route("plan", budget_left=-1) == GenMode.FAST
    assert route("plan", budget_left=10) == GenMode.SLOW


@pytest.mark.parametrize("stage", ["plan", "reflect", "review", "code", "parse", "test_gen"])
def test_route_returns_valid_mode(stage: str) -> None:
    assert route(stage) in (GenMode.FAST, GenMode.SLOW)
