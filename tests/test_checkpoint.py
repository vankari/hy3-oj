"""中断、检查点接口与人类反馈单测。

对应方案：①优雅中断 ②阶段级 checkpoint（预留接口）③人类反馈结构化。
"""
from __future__ import annotations

import pytest

from hy3_oj.core.checkpoint import (
    VALID_VERDICTS,
    FeedbackStore,
    GracefulInterrupt,
    HumanFeedback,
    StageCheckpoint,
)


def test_interrupt_sets_and_resets() -> None:
    gi = GracefulInterrupt()
    assert not gi.stopped
    gi.request_stop()
    assert gi.stopped
    gi.reset()
    assert not gi.stopped


def test_interrupt_context_restores_handlers() -> None:
    """退出 with 后应恢复原信号处理器（不影响后续代码）。"""
    import signal

    original = signal.getsignal(signal.SIGINT)
    with GracefulInterrupt():
        pass
    assert signal.getsignal(signal.SIGINT) is original


def test_interrupt_loop_semantics() -> None:
    """中断后循环应停止开新题，且已处理项保留（不丢结果）。"""
    gi = GracefulInterrupt()
    processed: list[int] = []
    for i in range(5):
        if gi.stopped:
            break
        processed.append(i)
        if i == 2:
            gi.request_stop()
    assert processed == [0, 1, 2]  # 第 3 项后停止，已处理保留


def test_checkpoint_save_load_clear(tmp_path) -> None:
    cp = StageCheckpoint(problem_id="p/1", stage="CODER", payload={"solutions": 3})
    p = cp.save(tmp_path)
    assert p.exists()

    loaded = StageCheckpoint.load("p/1", tmp_path)
    assert loaded is not None
    assert loaded.stage == "CODER"
    assert loaded.payload == {"solutions": 3}

    StageCheckpoint.clear("p/1", tmp_path)
    assert StageCheckpoint.load("p/1", tmp_path) is None


def test_checkpoint_missing_returns_none(tmp_path) -> None:
    """无检查点 → 返回 None（调用方回退全流程重跑，不报错）。"""
    assert StageCheckpoint.load("nope", tmp_path) is None


def test_checkpoint_sanitizes_id(tmp_path) -> None:
    """题 id 含空格/冒号时文件名安全（Windows 非法字符）。"""
    cp = StageCheckpoint(problem_id="leetcode:3265 A/B", stage="X")
    p = cp.save(tmp_path)
    assert p.exists()
    assert StageCheckpoint.load("leetcode:3265 A/B", tmp_path) is not None


def test_feedback_valid_verdicts() -> None:
    fb = HumanFeedback(problem_id="p1", verdict="false_positive", note="嵌套深度误报")
    assert fb.verdict in VALID_VERDICTS
    assert fb.to_dict()["verdict"] == "false_positive"
    assert "ts_human" in fb.to_dict()


def test_feedback_rejects_invalid_verdict() -> None:
    with pytest.raises(ValueError):
        HumanFeedback(problem_id="p1", verdict="maybe")


def test_feedback_store_roundtrip(tmp_path) -> None:
    store = FeedbackStore(tmp_path / "fb.jsonl")
    assert store.all() == []

    store.add(HumanFeedback("a", "real", reviewer="human1"))
    store.add(HumanFeedback("b", "false_positive", reviewer_version="v0.5"))
    store.add(HumanFeedback("a", "unsure", note="看不出来"))

    assert len(store.all()) == 3
    assert len(store.for_problem("a")) == 2


def test_feedback_stats_excludes_unsure(tmp_path) -> None:
    """误报率口径：unsure 不计入分母。"""
    store = FeedbackStore(tmp_path / "fb.jsonl")
    store.add(HumanFeedback("a", "real"))
    store.add(HumanFeedback("b", "false_positive"))
    store.add(HumanFeedback("c", "false_positive"))
    store.add(HumanFeedback("d", "unsure"))

    s = store.stats()
    assert s["counted"] == 3      # real + 2× false_positive
    assert s["unsure"] == 1
    assert s["false_positives"] == 2
    assert abs(s["fp_rate"] - 2 / 3) < 1e-9


def test_feedback_stats_empty(tmp_path) -> None:
    """无反馈时 fp_rate 为 None（而非 0，避免"零反馈"被误读为"零误报"）。"""
    assert FeedbackStore(tmp_path / "none.jsonl").stats()["fp_rate"] is None
