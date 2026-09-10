import asyncio

from hy3_oj.agents.planner import deep_analyze
from hy3_oj.core.schemas import Problem, Source
from hy3_oj.llm.client import ChatResult


def test_deep_analysis_uses_reasoning_when_content_is_empty():
    class Client:
        async def chat(self, *args, **kwargs):
            return ChatResult(content="", reasoning="Count only the fourth-root search interval.")

    problem = Problem(id="deep", source=Source.EXTERNAL, statement="Analyze the complexity.")
    assert asyncio.run(deep_analyze(Client(), problem)) == "Count only the fourth-root search interval."


def test_deep_analysis_prefers_final_analysis():
    class Client:
        async def chat(self, *args, **kwargs):
            return ChatResult(content="Final analysis", reasoning="Draft analysis")

    problem = Problem(id="deep", source=Source.EXTERNAL, statement="Analyze the complexity.")
    assert asyncio.run(deep_analyze(Client(), problem)) == "Final analysis"
