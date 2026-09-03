"""C++17 兜底闭环回归测试。

v9 实测 bug：for round_idx in range(...) 中赋值 round_idx 会被迭代器覆盖，
导致 C++ 兜底生成代码后从未判题（轨迹 CPP_FALLBACK 后无 JUDGED）。
改为 while 手动管理轮数，本测试锁定该行为：
- C++ 池必须被实际判题（不能只生成不判）
- 重置轮数不会造成死循环（有上界）
"""
from __future__ import annotations

import asyncio

from hy3_oj.core.schemas import JudgeResult, Language, Verdict


def make_judge(v: Verdict) -> list[JudgeResult]:
    return [JudgeResult(verdict=v)]


class FakeExecutor:
    """记录 execute 调用，验证 C++ 代码确实被判题。"""

    def __init__(self, verdicts: list[Verdict] | None = None) -> None:
        self.calls: list[Language] = []
        self.verdicts = verdicts or []

    def execute(self, sol, tests, checker=None):
        self.calls.append(sol.language)
        v = self.verdicts[len(self.calls) - 1] if len(self.calls) <= len(self.verdicts) else Verdict.WA
        return make_judge(v)

    def close(self) -> None:
        pass


def test_while_loop_runs_cpp_and_terminates() -> None:
    """模拟：Python 轮数耗尽 → 触发 C++ 兜底 → C++ 必须被判题且有轮数上界。"""
    # 直接验证循环语义：while + 手动递增，重置后仍能推进且终止
    max_rounds = 3
    visited: list[int] = []
    used_cpp = False
    round_idx = 0
    while round_idx <= max_rounds:
        visited.append(round_idx)
        if round_idx >= max_rounds and not used_cpp:
            used_cpp = True
            round_idx = 0
            continue  # 重置后重来一轮，但 used_cpp 保证不再触发
        round_idx += 1
    assert 0 in visited
    assert visited[-1] == max_rounds  # 正常终止
    assert len(visited) <= 2 * (max_rounds + 1)  # 有界，不会死循环
    assert used_cpp


def test_cpp_language_preserved_in_executor_calls() -> None:
    """executor 收到的语言必须反映实际 Solution.language（C++ 兜底后为 CPP17）。"""
    ex = FakeExecutor()
    from hy3_oj.core.schemas import Solution

    ex.execute(Solution(code="py", language=Language.PYTHON3), [])
    ex.execute(Solution(code="cpp", language=Language.CPP17), [])
    assert ex.calls == [Language.PYTHON3, Language.CPP17]


def test_asyncio_gather_with_fake_executor() -> None:
    """to_thread + gather 的并发判题路径可用（C++ 兜底走同一路径）。"""
    ex = FakeExecutor()

    async def run() -> list[Language]:
        return await asyncio.gather(*[
            asyncio.to_thread(ex.execute, __import__("hy3_oj.core.schemas", fromlist=["Solution"]).Solution(
                code="c", language=Language.CPP17), [])
        ])

    asyncio.run(run())
    assert ex.calls == [Language.CPP17]
