import asyncio
from pathlib import Path

import pytest

from hy3_oj.core.schemas import JudgeSpec, Problem, Source, Solution, TestCase, JudgeResult, Verdict, Plan
from hy3_oj.sandbox.checkers.integer_decomposition import optimal, check
from hy3_oj.sandbox.docker_executor import DockerExecutor


def test_small_oracle_and_counterexamples():
    from math import isqrt
    for n in range(101, 1001):
        expected = min(a+n//a+n%a for a in range(1, isqrt(n)+1))
        assert sum(optimal(n)) == expected
    assert sum(optimal(128)) == 24
    assert sum(optimal(130)) == 23
    assert check("130", "13 10 0")
    assert not check("128", "9 14 2")
    assert not check("130", "11 11 9")
    assert not check("130", "10 13 0 23")
    assert check("7489350167353676785", "2734129965 2739207815 310")
    assert not check("7489350167353676785", "2735289461 2738046658 5447")


def test_profile_roundtrip_and_limit_isolation():
    ex = object.__new__(DockerExecutor)
    ex.time_limit, ex.memory, ex._client = 5, "512m", object()
    spec = JudgeSpec(time_limit_s=1, memory_mb=256, checker="integer_decomposition", tests_complete=True)
    scoped = ex.with_limits(spec)
    assert (ex.time_limit, ex.memory) == (5, "512m")
    assert (scoped.time_limit, scoped.memory) == (1, "256m")
    assert scoped._client is ex._client
    problem = Problem(id="formal", source=Source.EXTERNAL, statement="s", judge=spec,
        public_tests=[TestCase(input="130", expected_output="10 13 0")])
    assert Problem.model_validate_json(problem.model_dump_json()) == problem
    with pytest.raises(ValueError):
        Problem(id="missing", source=Source.EXTERNAL, statement="s", judge=spec)


def test_registered_checker_cannot_be_bypassed_by_expected_text():
    ex = object.__new__(DockerExecutor)
    ex.strict_checker = True
    raw = {"exit_code": 0, "timed_out": False, "checker_ok": False,
           "stdout": "11 11 9", "stderr": "", "time_ms": 0}
    tests = [TestCase(input="130", expected_output="11 11 9")]
    assert ex._to_results([raw], tests)[0].verdict == Verdict.WA
    raw["checker_ok"] = None
    assert ex._to_results([raw], tests)[0].verdict == Verdict.RE


def test_complete_problem_skips_all_ai_test_generation(tmp_path, monkeypatch):
    from hy3_oj.core.pipeline import SolvePipeline
    from hy3_oj.core.config import load_config
    from hy3_oj.agents import tester, parser, planner, coder

    async def forbidden(*args, **kwargs):
        raise AssertionError("AI test generation must not run")
    for name in ("gen_tests", "gen_bf_tests", "gen_brute_force"):
        monkeypatch.setattr(tester, name, forbidden)
    async def parse(client, p):
        return p
    async def plan(*args, **kwargs):
        return Plan()
    async def generate(*args, **kwargs):
        return [Solution(code="print('13 10 0')")]
    monkeypatch.setattr(parser, "parse", parse)
    monkeypatch.setattr(planner, "plan", plan)
    monkeypatch.setattr(coder, "generate", generate)
    class Executor:
        def with_limits(self, spec):
            assert spec.time_limit_s == 1
            return self
        def execute(self, sol, tests, checker):
            assert "def check(" in checker
            return [JudgeResult(verdict=Verdict.AC) for _ in tests]
    cfg = load_config(overrides={"eval": {"runs_dir": str(tmp_path)}, "solve": {"n_diverse_plans": 1}})
    problem = Problem(id="formal", source=Source.EXTERNAL, statement="s", difficulty="easy",
        public_tests=[TestCase(input="130", expected_output="10 13 0")],
        judge=JudgeSpec(time_limit_s=1, memory_mb=256, checker="integer_decomposition", tests_complete=True))
    result = asyncio.run(SolvePipeline(cfg, client=object(), executor=Executor()).solve(problem))
    assert result["passed"]
    trace = Path(result["trace_file"]).read_text(encoding="utf-8")
    assert '"source": "provided"' in trace
    assert "tester fallback" not in trace
