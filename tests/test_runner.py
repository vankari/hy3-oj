"""批量评测驱动单测（断点续跑 / 异常重试 / 单题失败不中断整批）。

长批次跑批的关键保障：中断可 resume（重跑不重复消耗额度）、
基础设施抖动可重试（不被记成能力失败）、单题异常不中断整批。
"""
from __future__ import annotations

import asyncio

from hy3_oj.core.schemas import Plan, Problem, Source
from hy3_oj.eval import runner


def make_problem(pid: str) -> Problem:
    return Problem(id=pid, source=Source.CODECONTESTS, statement="s" * 200, difficulty="easy")


class FakePipeline:
    """按预设结果返回；可指定某些题抛异常（模拟沙箱/网络抖动）。"""

    def __init__(self, results: dict[str, dict], raises: dict[str, int] | None = None) -> None:
        self.results = results
        self.raises = raises or {}
        self.attempts: dict[str, int] = {}

    async def solve(self, p: Problem) -> dict:
        n = self.attempts.get(p.id, 0) + 1
        self.attempts[p.id] = n
        if p.id in self.raises and n <= self.raises[p.id]:
            raise RuntimeError(f"transient failure #{n}")
        return self.results[p.id]


def _rec_ok(pid: str) -> dict:
    return {"problem_id": pid, "difficulty": "easy", "passed": True, "rounds": 0, "code": "print(1)"}


def _rec_bad(pid: str) -> dict:
    return {"problem_id": pid, "difficulty": "easy", "passed": False, "rounds": 3, "code": "print(2)"}


def test_run_subset_appends_and_returns_all(tmp_path) -> None:
    out = tmp_path / "solve.jsonl"
    pipe = FakePipeline({"a": _rec_ok("a"), "b": _rec_bad("b")})
    recs = asyncio.run(runner.run_subset([make_problem("a"), make_problem("b")], pipe, out,
                                         concurrency=2, log=lambda *_: None))
    assert len(recs) == 2
    assert {r["problem_id"] for r in recs} == {"a", "b"}


def test_run_subset_resume_skips_done(tmp_path) -> None:
    """resume：已完成题目不重跑（避免重复消耗额度）。"""
    out = tmp_path / "solve.jsonl"
    pipe = FakePipeline({"a": _rec_ok("a"), "b": _rec_bad("b")})
    asyncio.run(runner.run_subset([make_problem("a")], pipe, out, log=lambda *_: None))
    # 第二次传入 a+b，但 a 已完成 → 只应跑 b
    asyncio.run(runner.run_subset([make_problem("a"), make_problem("b")], pipe, out, log=lambda *_: None))
    assert pipe.attempts == {"a": 1, "b": 1}  # a 未被重跑


def test_run_subset_no_resume_reruns_all(tmp_path) -> None:
    out = tmp_path / "solve.jsonl"
    pipe = FakePipeline({"a": _rec_ok("a")})
    asyncio.run(runner.run_subset([make_problem("a")], pipe, out, log=lambda *_: None))
    asyncio.run(runner.run_subset([make_problem("a")], pipe, out, resume=False, log=lambda *_: None))
    assert pipe.attempts["a"] == 2


def test_run_subset_retries_transient_errors(tmp_path) -> None:
    """抖动重试：第一次异常、第二次成功 → 记为正常结果而非错误。"""
    out = tmp_path / "solve.jsonl"
    pipe = FakePipeline({"a": _rec_ok("a")}, raises={"a": 1})
    recs = asyncio.run(runner.run_subset([make_problem("a")], pipe, out, retries=1, log=lambda *_: None))
    assert pipe.attempts["a"] == 2
    assert recs[0]["passed"] is True
    assert "error" not in recs[0]


def test_run_subset_records_error_after_retries_exhausted(tmp_path) -> None:
    """重试耗尽 → 记录 error 且不中断整批。"""
    out = tmp_path / "solve.jsonl"
    pipe = FakePipeline({"a": _rec_ok("a"), "bad": _rec_ok("bad")}, raises={"bad": 99})
    recs = asyncio.run(runner.run_subset([make_problem("a"), make_problem("bad")], pipe, out,
                                         retries=1, log=lambda *_: None))
    by_id = {r["problem_id"]: r for r in recs}
    assert by_id["a"]["passed"] is True
    assert "error" in by_id["bad"]  # 抖动被记录为 error，而非静默失败
    assert by_id["bad"]["passed"] is False


def test_load_jsonl_missing_file(tmp_path) -> None:
    assert runner.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_plan_from_trace_prefers_final_plan(tmp_path) -> None:
    """PLAN（末态）优先于 PLANNED（中间态）。"""
    tf = tmp_path / "t.jsonl"
    tf.write_text(
        '{"state": "PLANNED", "plan": {"approach": ["early"], "algorithm_tags": [], '
        '"time_complexity": "", "space_complexity": "", "edge_cases": []}}\n'
        '{"state": "PLAN", "plan": {"approach": ["final"], "algorithm_tags": ["dp"], '
        '"time_complexity": "O(n)", "space_complexity": "O(1)", "edge_cases": []}}\n',
        encoding="utf-8",
    )
    plan = runner.load_plan_from_trace(str(tf))
    assert isinstance(plan, Plan)
    assert plan.approach == ["final"]


def test_load_plan_from_trace_missing_file() -> None:
    assert runner.load_plan_from_trace("") is None
    assert runner.load_plan_from_trace("nonexistent.jsonl") is None
