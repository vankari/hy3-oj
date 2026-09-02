"""行为探针单测（fake client/executor，不依赖 Docker 与 LLM）。

核心防线：探针必须经官方参考解反向校验——参考解也过不了的"样例"是抽取噪音，丢弃。
"""
from __future__ import annotations

import asyncio
import json

from hy3_oj.agents import prober
from hy3_oj.core.schemas import Problem, Solution, Source, TestCase


class FakeClient:
    """返回预置的样例抽取 JSON。"""

    def __init__(self, payload: str):
        self.payload = payload

    async def chat(self, messages, **kwargs):  # noqa: ARG002
        class R:
            content = ""

        r = R()
        r.content = self.payload
        return r


class FakeExecutor:
    """按代码内容路由预置输出。"""

    def __init__(self, outputs_by_code: dict[str, list[str]]):
        self.outputs_by_code = outputs_by_code

    def run_stdout(self, solution: Solution, inputs: list[str]) -> list[str]:  # noqa: ARG002
        return self.outputs_by_code[solution.code]


def make_problem(with_ref: bool = True) -> Problem:
    return Problem(
        id="px", source=Source.CODECONTESTS, statement="题面",
        reference_solutions=["REF_CODE"] if with_ref else [],
    )


def test_probe_fires_when_candidate_fails_and_reference_passes() -> None:
    problem = make_problem()
    client = FakeClient('[{"input": "AABCC\\n", "output": "Yes\\n"}]')
    executor = FakeExecutor({
        "REF_CODE": ["Yes\n"],
        "CAND_CODE": ["No\n"],  # p01811 场景：官方样例上行为错误
    })
    flags = asyncio.run(prober.probe(client, executor, problem, Solution(code="CAND_CODE")))
    assert flags and "probe_fail" in flags[0]


def test_probe_discards_untrustworthy_extraction() -> None:
    # 358_B 场景：抽取到的"样例"连官方参考解都过不了 → 噪音，丢弃
    problem = make_problem()
    client = FakeClient('[{"input": "x\\n", "output": "no\\n"}]')
    executor = FakeExecutor({
        "REF_CODE": ["yes\n"],   # 参考解输出与抽取的预期不符 → 探针不可信
        "CAND_CODE": ["yes\n"],
    })
    flags = asyncio.run(prober.probe(client, executor, problem, Solution(code="CAND_CODE")))
    assert flags == []


def test_probe_silent_without_reference() -> None:
    problem = make_problem(with_ref=False)
    client = FakeClient('[{"input": "a\\n", "output": "b\\n"}]')
    executor = FakeExecutor({"CAND_CODE": ["c\n"]})
    flags = asyncio.run(prober.probe(client, executor, problem, Solution(code="CAND_CODE")))
    assert flags == []


def test_extract_caches_to_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(prober, "_CACHE_DIR", tmp_path)
    problem = make_problem()
    client = FakeClient('[{"input": "1\\n", "output": "2\\n"}]')
    tests = asyncio.run(prober.extract_statement_samples(client, problem))
    assert len(tests) == 1 and tests[0].input == "1\n"
    # 第二次应命中缓存（client 换了 payload 也不变）
    client2 = FakeClient("[]")
    tests2 = asyncio.run(prober.extract_statement_samples(client2, problem))
    assert len(tests2) == 1
    # 缓存文件是合法 JSON
    cached = json.loads((tmp_path / "px.json").read_text(encoding="utf-8"))
    assert cached[0]["expected_output"] == "2\n"
