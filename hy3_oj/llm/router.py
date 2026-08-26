"""快/慢思考调度策略（骨架）。

策略接口：route(stage, difficulty, fail_rounds, budget) -> GenMode
默认规则：规划/归因/过程审查 → 慢思考；生成/改写/解析 → 快思考；
难度升级或连续失败时升格慢思考。策略参数化以支持调度消融（重点技术 1）。
TODO(D8): 实现默认策略与难度感知升格规则。
"""
from __future__ import annotations

from hy3_oj.core.schemas import GenMode

SLOW_STAGES = {"plan", "reflect", "review"}


def route(stage: str, difficulty: str | None = None, fail_rounds: int = 0, budget_left: int = 1) -> GenMode:
    """默认调度策略（占位实现）。"""
    if budget_left <= 0:
        return GenMode.FAST
    if stage in SLOW_STAGES:
        return GenMode.SLOW
    if difficulty == "hard" or fail_rounds >= 2:
        return GenMode.SLOW
    return GenMode.FAST
