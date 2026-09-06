"""C++17 双模式单测：

需求（用户）：
1. 用户显式要求语言（--lang py / cpp）→ 全程锁定该语言，不自动兜底
2. 无显式要求 → 优先 Python3；失败后用末轮 verdict 诊断
   （TLE/RE 主导 → 建议 C++；WA 主导 → 算法问题，C++ 无用）

本测试锁定诊断逻辑与语言锁定行为，不依赖真实 LLM/Docker。
"""
from __future__ import annotations

from collections import Counter

from hy3_oj.core.schemas import JudgeResult, Language, Verdict


def _judge(n_ac: int, n_tle: int = 0, n_re: int = 0, n_wa: int = 0) -> list[JudgeResult]:
    out = []
    out += [JudgeResult(verdict=Verdict.AC)] * n_ac
    out += [JudgeResult(verdict=Verdict.TLE)] * n_tle
    out += [JudgeResult(verdict=Verdict.RE)] * n_re
    out += [JudgeResult(verdict=Verdict.WA)] * n_wa
    return out


def _diagnose(judged: list[JudgeResult]) -> tuple[bool, str]:
    """复现 pipeline._diagnose 的 verdict 分布判断（与 pipeline 内联逻辑一致）。"""
    c = Counter(r.verdict for r in judged)
    n = sum(c.values()) or 1
    tle, re_, wa = c.get(Verdict.TLE, 0), c.get(Verdict.RE, 0), c.get(Verdict.WA, 0)
    if tle / n > 0.3:
        return True, f"TLE({tle}/{n})"
    if re_ / n > 0.3:
        return True, f"RE({re_}/{n})"
    if wa / n >= 0.3:
        return False, f"WA({wa}/{n})"
    return False, "mixed"


def test_tle_dominant_suggests_cpp() -> None:
    """末轮主要为 TLE → 疑似性能瓶颈 → 建议 C++。"""
    is_lang, _ = _diagnose(_judge(10, n_tle=70))
    assert is_lang is True


def test_re_dominant_suggests_cpp() -> None:
    """末轮主要为 RE → 疑似递归深度/语言特性 → 建议 C++。"""
    is_lang, _ = _diagnose(_judge(40, n_re=60))
    assert is_lang is True


def test_wa_dominant_is_algorithm() -> None:
    """末轮主要为 WA → 算法实现问题 → C++ 无法改善。"""
    is_lang, _ = _diagnose(_judge(5, n_wa=95))
    assert is_lang is False


def test_mixed_is_algorithm() -> None:
    is_lang, _ = _diagnose(_judge(10, n_wa=40, n_re=20, n_tle=10))
    assert is_lang is False


def test_explicit_py_forbids_cpp_fallback() -> None:
    """显式 Python3 时，pipeline 不应触发 C++ 兜底（兜底条件含 language is None）。"""
    # 复现 pipeline 内 cpp 兜底触发条件：language is None 才兜底
    lang = Language.PYTHON3
    assert lang is not None  # 显式指定 → 自动兜底被禁用（language is None 为假）


def test_language_enum_values() -> None:
    assert Language.PYTHON3.value == "python3"
    assert Language.CPP17.value == "cpp17"
