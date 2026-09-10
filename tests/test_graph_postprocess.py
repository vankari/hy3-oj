"""GUI 后处理必须将过程审查证据传递给题解，不能用测试通过覆盖审查失败。"""
import asyncio

import pytest

from hy3_oj.agents import explainer, reviewer
from hy3_oj.core.schemas import (
    Language, Plan, Problem, ProcessReview, ReviewStep, Source, StepVerdict,
)
from hy3_oj.graph import orchestrator
from hy3_oj.core.assessment import explanation_hash


def test_single_dataset_upload_preserves_official_tests(tmp_path):
    from hy3_oj.core.schemas import TestCase

    problem = Problem(id="official", source=Source.LIVECODEBENCH, statement="dataset problem",
        difficulty="hard", public_tests=[TestCase(input="1", expected_output="2")],
        private_tests=[TestCase(input="9", expected_output="10")])
    path = tmp_path / "single.jsonl"
    path.write_text(problem.model_dump_json() + "\n", encoding="utf-8")
    route, restored, hint = orchestrator.route_input("", str(path))
    assert route == "single" and restored == problem and hint is None
    path.write_text((problem.model_dump_json() + "\n") * 2, encoding="utf-8")
    assert orchestrator.route_input("", str(path))[0] == "batch"
    path.write_text("", encoding="utf-8")
    assert orchestrator.route_input("", str(path))[0] == "clarify"


@pytest.mark.parametrize("review_error", [False, True])
def test_postprocess_forwards_review_plan_and_language(monkeypatch, review_error):
    from hy3_oj.llm import client
    from hy3_oj.sandbox import docker_executor

    class Client:
        def __init__(self, cfg):
            pass

        async def close(self):
            pass

    class Executor:
        def __init__(self, cfg):
            pass

        def close(self):
            pass

    monkeypatch.setattr(client, "Hy3Client", Client)
    monkeypatch.setattr(docker_executor, "DockerExecutor", Executor)
    plan = Plan(time_complexity="O(N^0.5)")
    review = ProcessReview(step_verdicts=[StepVerdict(
        step=step, passed=step != ReviewStep.COMPLEXITY_PROOF,
        evidence="O(N^0.5) exceeds the required O(N^0.25)",
    ) for step in ReviewStep], error_step=ReviewStep.COMPLEXITY_PROOF,
        explanation_sha256=explanation_hash("candidate analysis"))
    calls = {}

    async def fake_review(client, problem, actual_plan, solution, verdict, **kw):
        assert actual_plan == plan
        assert solution.language == Language.CPP17
        assert calls["generated"]
        assert kw["material"].explanation == "candidate analysis"
        assert verdict == ""
        if review_error:
            raise RuntimeError("review unavailable")
        return review

    async def fake_explain(client, problem, solution, **kw):
        calls.update(kw)
        calls["generated"] = True
        assert solution.language == Language.CPP17
        return "candidate analysis"

    monkeypatch.setattr(reviewer, "review", fake_review)
    monkeypatch.setattr(explainer, "explain", fake_explain)
    problem = Problem(id="complexity", source=Source.EXTERNAL, statement="Require O(N^0.25)")
    res = dict(code="int main() {}", passed=True, language_used="cpp17", plan=plan.model_dump())
    out = asyncio.run(orchestrator._postprocess({}, problem, res))
    assert calls.get("review") is None
    assert calls["plan"] == plan
    assert calls["language_hint"] == "C++17"
    assert "外部题的 AI 生成测试全部通过" in calls["judge_summary"]
    assert "每个测试限时" in calls["judge_summary"]
    assert out["passed"] is True
    if review_error:
        assert "error" in out["review"]
        assert out["assessment"]["process_status"] == "error"
    else:
        assert out["review"]["error_step"] == ReviewStep.COMPLEXITY_PROOF.value
        assert out["assessment"]["combined_status"] == "answer_only"
