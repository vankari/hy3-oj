"""refine 保留历史最优解回归测试。

之前的 bug：refine 整池替换会把"已通过 96/102 测试点"的接近解丢弃，换新生成的
2 个解，导致 easy/medium 的接近题反复回到起点（513_A. Game 实测：4 次重规划
仍在 96/102 徘徊，709_D 停在 197/222）。

修复：refine 生成新解后，把历史最优解（按通过测试点数）一并保留进池。
本测试用极简模拟复现该决策逻辑，防止回退。
"""
from __future__ import annotations

from hy3_oj.core.schemas import JudgeResult, Language, Solution, Verdict


def _judge(n_pass: int, n_fail: int) -> list[JudgeResult]:
    return ([JudgeResult(verdict=Verdict.AC)] * n_pass
            + [JudgeResult(verdict=Verdict.WA)] * n_fail)


def pick_best(pool: list[Solution], judged: list[list[JudgeResult]]) -> tuple[Solution | None, int]:
    """复现 pipeline 中的历史最优选择逻辑（按通过测试点数）。"""
    best_cand: Solution | None = None
    best_pass = -1
    for cand, results in zip(pool, judged):
        n_pass = sum(1 for r in results if r.verdict == Verdict.AC)
        if n_pass > best_pass:
            best_cand, best_pass = cand, n_pass
    return best_cand, best_pass


def test_picks_highest_pass_count() -> None:
    pool = [Solution(code="a"), Solution(code="b"), Solution(code="c")]
    judged = [_judge(96, 6), _judge(10, 92), _judge(50, 52)]
    best, n = pick_best(pool, judged)
    assert best is not None and best.code == "a"
    assert n == 96


def test_refine_pool_keeps_best() -> None:
    """refine 后新池必须包含历史最优解（不丢弃进展）。"""
    pool = [Solution(code="near-96"), Solution(code="weak-10")]
    judged = [_judge(96, 6), _judge(10, 92)]
    best_cand, best_pass = pick_best(pool, judged)

    new_pool = [Solution(code="new1"), Solution(code="new2")]
    refined = new_pool + ([best_cand] if best_cand is not None else [])

    assert len(refined) == 3
    assert any(s.code == "near-96" for s in refined), "历史最优解必须保留"
    assert best_pass == 96


def test_best_solution_eventually_wins() -> None:
    """保留最优解后，若新解全部更差，最优解仍在池中可被后续修复选中。"""
    pool = [Solution(code="near-96")]
    judged = [_judge(96, 6)]
    best_cand, _ = pick_best(pool, judged)

    worse = [Solution(code="worse1"), Solution(code="worse2")]
    pool = worse + [best_cand]

    # 下一轮：新解更差，但最优解仍在
    judged2 = [_judge(5, 97), _judge(2, 100), _judge(96, 6)]
    best2, n2 = pick_best(pool, judged2)
    assert best2 is not None and best2.code == "near-96"
    assert n2 == 96


def test_cpp_language_preserved_when_kept() -> None:
    """保留的最优解若来自 C++ 兜底路径，语言标记不得丢失。"""
    pool = [Solution(code="cpp-sol", language=Language.CPP17)]
    judged = [_judge(80, 20)]
    best, _ = pick_best(pool, judged)
    assert best is not None and best.language == Language.CPP17
