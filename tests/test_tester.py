"""Tester 单测：边界用例生成 + 暴力 oracle 验证 + 差分对拍（不调用 LLM）。

关键行为：
- 生成的用例必须有换行结尾（喂给 stdin）
- LLM 异常时返回空列表而非抛出（闭环不中断）
- 暴力解必须通过样例验证才可用（防"错误 oracle"污染对拍）
- 差分对拍能识别不一致
"""
from __future__ import annotations

import asyncio

from hy3_oj.agents import tester
from hy3_oj.core.schemas import Problem, Source, TestCase


def make_problem() -> Problem:
    return Problem(
        id="p1",
        source=Source.CODECONTESTS,
        statement="Given n integers, output their sum.",
        samples=[TestCase(input="3\n1 2 3\n", expected_output="6\n")],
    )


class FakeClient:
    def __init__(self, reply: str, raise_exc: bool = False) -> None:
        self.reply = reply
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def chat(self, messages, mode=None, temperature=None, max_tokens=None, stage=None):
        self.calls.append({"stage": stage, "mode": mode})
        if self.raise_exc:
            raise RuntimeError("api down")

        class R:
            content = __import__("json").dumps([]) if not self.reply else self.reply

        return R()


def test_gen_tests_parses_json_array() -> None:
    client = FakeClient('[{"input": "1\\n5"}, {"input": "2\\n1 2"}]')
    tests = asyncio.run(tester.gen_tests(client, make_problem(), n=2))
    assert len(tests) == 2
    assert tests[0].input.endswith("\n")  # 喂 stdin 需换行
    assert tests[0].is_ai_generated
    assert client.calls[0]["stage"] == "test_gen"


def test_gen_tests_skips_empty_input() -> None:
    client = FakeClient('[{"input": "  "}, {"input": "1\\n5"}]')
    tests = asyncio.run(tester.gen_tests(client, make_problem(), n=2))
    assert len(tests) == 1


def test_gen_tests_handles_api_error() -> None:
    client = FakeClient("", raise_exc=True)
    assert asyncio.run(tester.gen_tests(client, make_problem())) == []


def test_gen_tests_handles_bad_json() -> None:
    client = FakeClient("I cannot produce JSON")
    assert asyncio.run(tester.gen_tests(client, make_problem())) == []


class FakeExecutor:
    """模拟执行器：按 code 内容返回预设输出。"""

    def __init__(self, outputs: dict[str, list[str | None]]) -> None:
        self.outputs = outputs

    def run_stdout(self, sol, inputs, **kw):
        # 提取的代码常带尾部换行（正则捕获），故 strip 后再查表
        return self.outputs.get((sol.code or "").strip(), [None] * len(inputs))


def test_brute_force_rejected_when_sample_mismatch() -> None:
    """暴力解样例不过 → 不可信，必须返回 None（防错误 oracle 污染对拍）。"""
    client = FakeClient("```python\nprint(999)\n```")
    ex = FakeExecutor({"print(999)": ["999\n"]})  # 与期望 6 不符
    assert asyncio.run(tester.gen_brute_force(client, make_problem(), ex, use_cache=False)) is None


def test_brute_force_accepted_when_sample_passes(tmp_path, monkeypatch) -> None:
    client = FakeClient("```python\nprint(6)\n```")
    ex = FakeExecutor({"print(6)": ["6\n"]})
    # monkeypatch 而非直接赋值：避免污染模块状态影响其他测试
    monkeypatch.setattr(tester, "_BRUTE_CACHE", tmp_path)
    code = asyncio.run(tester.gen_brute_force(client, make_problem(), ex, use_cache=False))
    # 正则捕获的代码保留尾部换行，比对时 strip
    assert code is not None and code.strip() == "print(6)"
    assert (tmp_path / "p1.py").exists()  # 已缓存


def test_differential_mismatches_detects_diff() -> None:
    ex = FakeExecutor({
        "cand": ["6\n", "3\n"],   # 第二组与 brute 不一致
        "brute": ["6\n", "10\n"],
    })
    mm = tester.differential_mismatches(ex, "cand", "brute", ["a", "b"])
    assert len(mm) == 1
    assert mm[0]["input"] == "b"
    assert mm[0]["candidate"].strip() == "3"  # 存原始输出（含换行）
    assert mm[0]["brute"].strip() == "10"


def test_differential_mismatches_empty_inputs() -> None:
    ex = FakeExecutor({})
    assert tester.differential_mismatches(ex, "c", "b", []) == []


def test_differential_handles_execution_failure() -> None:
    """执行失败（输出 None）时不崩溃，且标记为 no_output（不作为"答案错误"证据）。"""
    ex = FakeExecutor({})  # 无预设 → 返回 [None]
    mm = tester.differential_mismatches(ex, "c", "b", ["x"])
    assert len(mm) == 1
    assert mm[0]["no_output"] is True
    assert mm[0]["candidate"] == ""  # None 被安全转为空串
