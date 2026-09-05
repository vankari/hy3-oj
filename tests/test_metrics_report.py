"""评测指标与报告单测（任务书 R8：pass@k、难度分桶、分层报告）。

pass_at_k 用组合估计 1 - C(n-c, k)/C(n, k)（无偏，见 AlphaCode/HumanEval）。
report.summarize_by_difficulty 为分层汇总（答案正确率 / 过程正确率 / 五段正确率 /
错误类型分布 / 蒙对定罪 / 能力临界点），render_markdown 渲染进技术报告。
"""
from __future__ import annotations

import math

from hy3_oj.eval import report
from hy3_oj.eval.metrics import bucket_by_difficulty, pass_at_k


def test_pass_at_k_perfect() -> None:
    assert pass_at_k(5, 5, 1) == 1.0
    assert pass_at_k(5, 5, 5) == 1.0


def test_pass_at_k_zero() -> None:
    assert pass_at_k(5, 0, 1) == 0.0


def test_pass_at_k_known_values() -> None:
    # n=6,c=3,k=1 → 3/6
    assert math.isclose(pass_at_k(6, 3, 1), 0.5)
    # k=2 → 1 - C(3,2)/C(6,2) = 1 - 3/15 = 0.8
    assert math.isclose(pass_at_k(6, 3, 2), 0.8, rel_tol=1e-6)
    # k=3 → 1 - C(3,3)/C(6,3) = 1 - 1/20 = 0.95
    assert math.isclose(pass_at_k(6, 3, 3), 0.95, rel_tol=1e-6)


def test_pass_at_k_k_exceeds_failure_headroom() -> None:
    """n-c < k 时必有采样命中 → 1.0。"""
    assert pass_at_k(6, 4, 3) == 1.0


def test_pass_at_k_monotonic_in_k() -> None:
    vals = [pass_at_k(10, 3, k) for k in (1, 2, 4, 8)]
    assert all(a <= b + 1e-9 for a, b in zip(vals, vals[1:]))


def test_bucket_by_difficulty() -> None:
    recs = [
        {"difficulty": "easy", "passed": True},
        {"difficulty": "hard", "passed": False},
        {"difficulty": "easy", "passed": False},
        {"passed": True},  # 无 difficulty → unknown
    ]
    b = bucket_by_difficulty(recs)
    assert len(b["easy"]) == 2
    assert len(b["hard"]) == 1
    assert len(b["unknown"]) == 1


def _solve_rows() -> list[dict]:
    return [
        {"problem_id": "a", "difficulty": "easy", "passed": True, "rounds": 0},
        {"problem_id": "b", "difficulty": "easy", "passed": False, "rounds": 3},
        {"problem_id": "c", "difficulty": "hard", "passed": False, "rounds": 4},
    ]


def _review_rows() -> list[dict]:
    return [
        {"problem_id": "a", "answer_passed": True, "process_score": 1.0, "lucky_pass_flags": [],
         "error_step": None, "error_type": None,
         "step_verdicts": [{"step": "题意理解", "passed": True},
                           {"step": "算法选型", "passed": True}]},
        {"problem_id": "b", "answer_passed": False, "process_score": 0.4, "lucky_pass_flags": [],
         "error_step": "边界处理", "error_type": "边界遗漏",
         "step_verdicts": [{"step": "边界处理", "passed": False}]},
        {"problem_id": "c", "answer_passed": False, "process_score": 0.3, "lucky_pass_flags": [],
         "error_step": "复杂度论证", "error_type": "复杂度误判",
         "step_verdicts": [{"step": "复杂度论证", "passed": False}]},
    ]


def test_summarize_by_difficulty() -> None:
    s = report.summarize_by_difficulty(_solve_rows(), _review_rows())
    assert s["overall"]["n"] == 3
    assert s["overall"]["answer_passed"] == 1
    assert math.isclose(s["overall"]["answer_acc"], 1 / 3)
    # 过程成立阈值 0.8 → 仅 a 成立
    assert s["overall"]["process_ok"] == 1
    assert math.isclose(s["overall"]["process_acc"], 1 / 3)
    # 错误类型分布
    assert s["overall"]["error_types"]["边界遗漏"] == 1
    assert s["overall"]["error_types"]["复杂度误判"] == 1


def test_summarize_detects_difficulty_drop() -> None:
    """能力临界点：easy 50% → hard 0%，跌幅 50pt。"""
    s = report.summarize_by_difficulty(_solve_rows(), _review_rows())
    drops = s["difficulty_drops"]
    assert drops
    assert drops[0]["from"] == "easy" and drops[0]["to"] == "hard"
    assert math.isclose(drops[0]["answer_drop_pt"], 50.0)


def test_summarize_without_reviews() -> None:
    """无审查记录时过程类分母为 0，不应除零崩溃。"""
    s = report.summarize_by_difficulty(_solve_rows(), [])
    assert s["overall"]["reviewed"] == 0
    assert s["overall"]["process_acc"] == 0.0


def test_summarize_lucky_conviction() -> None:
    """AC 且被行为探针定罪 → 蒙对定罪计数。"""
    solves = [{"problem_id": "a", "difficulty": "easy", "passed": True, "rounds": 0}]
    reviews = [{"problem_id": "a", "answer_passed": True, "process_score": 0.1,
                "lucky_pass_flags": ["probe_mismatch"], "error_step": "实现一致性",
                "error_type": "实现逻辑错误", "step_verdicts": []}]
    s = report.summarize_by_difficulty(solves, reviews)
    assert s["overall"]["lucky_convictions"] == 1
    assert s["overall"]["lucky_rate_of_ac"] == 1.0


def test_render_markdown_contains_sections() -> None:
    s = report.summarize_by_difficulty(_solve_rows(), _review_rows())
    md = report.render_markdown(s, meta={"数据集": "测试"})
    assert "分层主结果" in md
    assert "五段式逐段正确率" in md
    assert "过程错误类型分布" in md
    assert "能力临界点" in md
    assert "测试" in md  # meta
    assert "50.0%" in md or "33.3%" in md


def test_render_markdown_empty() -> None:
    md = report.render_markdown(report.summarize_by_difficulty([], []))
    assert "分层主结果" in md  # 空数据也应渲染出结构
