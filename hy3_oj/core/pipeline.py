"""解题闭环状态机（骨架）。

状态转移（详见 docs/项目架构设计.md §3.2）：
PARSED → PLANNED → GENERATED → LOCAL_TESTED → JUDGED(AC→DONE)
   ↑              失败 → REFLECTED → PATCHED → LOCAL_TESTED（轮数+1）
   └── 连续失败≥2 时 refine 重规划

退出条件：AC / 修复轮数达 N / token 预算耗尽；每次转移向 runs/<problem_id>.jsonl 追加事件。
TODO(D7): 实现 solve(problem) 主流程，串联 agents 与 sandbox。
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    PARSED = "PARSED"
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    LOCAL_TESTED = "LOCAL_TESTED"
    JUDGED = "JUDGED"
    REFLECTED = "REFLECTED"
    PATCHED = "PATCHED"
    DONE = "DONE"
    FAILED = "FAILED"


class SolvePipeline:
    """单题闭环解题编排器（待实现）。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.max_rounds: int = config["solve"]["max_repair_rounds"]
        self.token_budget: int = config["solve"]["token_budget_per_problem"]

    # async def solve(self, problem: Problem) -> Solution | None: ...
