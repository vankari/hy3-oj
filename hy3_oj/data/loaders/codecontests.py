"""CodeContests 加载器（评测基准第一优先级）。

HF deepmind/code_contests：description→statement；public/private/generated_tests
直接可用（本地判题完全可控）；cf_rating/difficulty 字段作难度分层依据（任务书 R2）；
solutions 字段的官方参考解用于 bug 注入验证（任务书 R7）。

实现要点：
- 默认 streaming=True 流式读取，避免全量下载（全集约 8GB）；
- HF 直连失败时设置环境变量 HF_ENDPOINT=https://hf-mirror.com 走镜像；
- 过滤无可用测试或题面过短的样本。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from hy3_oj.core.schemas import Problem, Source, TestCase

# CodeContests difficulty 枚举 → 三档分桶（分层依据，任务书 R2）
_DIFFICULTY_MAP = {1: "easy", 2: "medium", 3: "hard", 4: "hard", 5: "hard"}

# solutions/incorrect_solutions 的 language 枚举（取 PYTHON3=3 作参考解）
_LANG_PYTHON3 = 3

MIN_STATEMENT_LEN = 100  # 过滤过短题面（多为损坏样本）


def _to_test_cases(tests: dict[str, Any] | None, is_ai_generated: bool = False) -> list[TestCase]:
    """CodeContests tests 字段 {"input": [...], "output": [...]} → TestCase 列表。"""
    if not tests:
        return []
    inputs, outputs = tests.get("input") or [], tests.get("output") or []
    return [
        TestCase(input=str(i), expected_output=str(o), is_ai_generated=is_ai_generated)
        for i, o in zip(inputs, outputs)
    ]


def map_difficulty(raw: dict[str, Any]) -> str:
    """优先 difficulty 枚举；为 0（未知）时用 cf_rating 兜底（<1400 easy, <1900 medium, 其余 hard）。"""
    diff = raw.get("difficulty") or 0
    if diff in _DIFFICULTY_MAP:
        return _DIFFICULTY_MAP[diff]
    rating = raw.get("cf_rating") or 0
    if rating and rating < 1400:
        return "easy"
    if rating and rating < 1900:
        return "medium"
    return "hard"


def to_problem(raw: dict[str, Any]) -> Problem | None:
    """单条原始记录 → Problem；缺测试或题面过短返回 None。"""
    statement = (raw.get("description") or "").strip()
    if len(statement) < MIN_STATEMENT_LEN:
        return None

    public_tests = _to_test_cases(raw.get("public_tests"))
    private_tests = _to_test_cases(raw.get("private_tests"))
    generated_tests = _to_test_cases(raw.get("generated_tests"), is_ai_generated=True)
    if not (public_tests or private_tests or generated_tests):
        return None

    solutions = raw.get("solutions") or {}
    ref_solutions = [
        s
        for lang, s in zip(solutions.get("language") or [], solutions.get("solution") or [])
        if lang == _LANG_PYTHON3
    ]

    return Problem(
        id=str(raw.get("name") or f"cc-{raw.get('cf_contest_id', 'x')}-{raw.get('cf_index', 'x')}"),
        source=Source.CODECONTESTS,
        statement=statement,
        samples=public_tests[:3],  # 题面样例取 public 前 3 个
        difficulty=map_difficulty(raw),
        tags=list(raw.get("cf_tags") or []),
        public_tests=public_tests,
        private_tests=private_tests,
        generated_tests=generated_tests,
        reference_solutions=ref_solutions[:3],
    )


def iter_problems(split: str = "train", limit: int | None = None, streaming: bool = True) -> Iterator[Problem]:
    """流式迭代 CodeContests，产出合法 Problem。

    HF 直连不可用时：
        set HF_ENDPOINT=https://hf-mirror.com 后重试（或配置代理 127.0.0.1:1028）。
    """
    from datasets import load_dataset  # 延迟导入，避免无关模块加载 datasets

    if os.environ.get("HF_ENDPOINT"):
        os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

    ds = load_dataset("deepmind/code_contests", split=split, streaming=streaming)
    seen: set[str] = set()
    n = 0
    for raw in ds:
        problem = to_problem(raw)
        if problem is None or problem.id in seen:
            continue
        seen.add(problem.id)
        yield problem
        n += 1
        if limit is not None and n >= limit:
            return
