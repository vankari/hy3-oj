"""LCB loader 单测（合成记录，不依赖网络）。"""
from __future__ import annotations

import base64
import json
import pickle
import zlib

from hy3_oj.data.loaders.livecodebench import _decode_private, _norm_expected, to_problem


def _row(**kw) -> dict:
    base = {
        "question_content": "Given an array, return the sum. " * 10,
        "platform": "leetcode",
        "question_id": "1",
        "question_title": "two-sum",
        "difficulty": "easy",
        "starter_code": "",
        "metadata": "{}",
        "public_test_cases": json.dumps([{"input": "[2,7,11,15]\n9", "output": "[0, 1]", "testtype": "stdin"}]),
        "private_test_cases": "",
    }
    base.update(kw)
    return base


def test_stdin_problem_basic() -> None:
    p = to_problem(_row())
    assert p is not None and p.source.value == "livecodebench"
    assert p.difficulty == "easy"
    assert len(p.public_tests) == 1
    assert "call-based" not in p.statement


def test_call_based_statement_and_json_norm() -> None:
    p = to_problem(_row(
        starter_code="class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:",
        metadata='{"func_name": "twoSum"}',
    ))
    assert p is not None
    assert "call-based" in p.statement
    assert "json.dumps(Solution().twoSum(*args))" in p.statement
    # 预期输出 canonical JSON 化（与驱动 json.dumps 对齐）
    assert p.public_tests[0].expected_output == "[0, 1]"


def test_norm_expected_python_literal() -> None:
    # Python 风格 True/元组也能规范化
    assert _norm_expected("True", True) == "true"
    assert _norm_expected("(1, 2)", True) == "[1, 2]"
    assert _norm_expected("not-a-literal", True) == "not-a-literal"
    assert _norm_expected("raw\n", False) == "raw\n"


def test_decode_private_pickle() -> None:
    cases = [{"input": "1\n", "output": "2\n"}]
    # 官方实测结构：base64 → zlib → pickle → JSON 字符串 → list
    raw = base64.b64encode(zlib.compress(pickle.dumps(json.dumps(cases)))).decode()
    assert _decode_private(raw) == cases
    # 兜底：pickle 直接包 list 也兼容
    raw2 = base64.b64encode(zlib.compress(pickle.dumps(cases))).decode()
    assert _decode_private(raw2) == cases


def test_decode_private_json_fallback() -> None:
    cases = [{"input": "1\n", "output": "2\n"}]
    assert _decode_private(json.dumps(cases)) == cases


def test_filter_short_statement() -> None:
    assert to_problem(_row(question_content="too short")) is None
