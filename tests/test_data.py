"""loader 与分层抽样子测（不依赖网络，用合成记录）。"""
from __future__ import annotations

from hy3_oj.core.schemas import Problem, Source
from hy3_oj.data.loaders.codecontests import map_difficulty, to_problem
from hy3_oj.data.subset import make_subset

RAW = {
    "name": "cf-1-A",
    "description": "给定 n 个整数，求它们的和。" * 10,
    "public_tests": {"input": ["3\n1 2 3\n"], "output": ["6\n"]},
    "private_tests": {"input": ["1\n5\n"], "output": ["5\n"]},
    "generated_tests": {"input": [], "output": []},
    "difficulty": 1,
    "cf_rating": 800,
    "cf_tags": ["math"],
    "solutions": {"language": [3, 2], "solution": ["print(sum(...))", "cpp-code"]},
}


def test_to_problem_mapping() -> None:
    p = to_problem(RAW)
    assert p is not None
    assert p.id == "cf-1-A"
    assert p.source == Source.CODECONTESTS
    assert p.difficulty == "easy"
    assert len(p.public_tests) == 1 and len(p.private_tests) == 1
    assert p.reference_solutions == ["print(sum(...))"]  # 仅保留 PYTHON3 参考解
    assert p.samples[0].expected_output == "6\n"


def test_to_problem_filters() -> None:
    assert to_problem({**RAW, "description": "短"}) is None  # 题面过短
    no_tests = {**RAW, "public_tests": {"input": [], "output": []}, "private_tests": {"input": [], "output": []}}
    assert to_problem(no_tests) is None  # 无任何测试


def test_map_difficulty_fallback() -> None:
    assert map_difficulty({"difficulty": 0, "cf_rating": 1000}) == "easy"
    assert map_difficulty({"difficulty": 0, "cf_rating": 1600}) == "medium"
    assert map_difficulty({"difficulty": 0, "cf_rating": 2200}) == "hard"
    assert map_difficulty({"difficulty": 5}) == "hard"


def _fake_problems(n: int, difficulty: str) -> list[Problem]:
    return [
        Problem(id=f"{difficulty}-{i}", source=Source.CODECONTESTS, statement="x" * 200, difficulty=difficulty)
        for i in range(n)
    ]


def test_make_subset_stratified_and_seeded() -> None:
    pool = _fake_problems(100, "easy") + _fake_problems(100, "medium") + _fake_problems(100, "hard")
    s1 = make_subset(pool, total=60, seed=42)
    s2 = make_subset(pool, total=60, seed=42)
    assert [p.id for p in s1] == [p.id for p in s2]  # 同 seed 可复现
    counts = {}
    for p in s1:
        counts[p.difficulty] = counts.get(p.difficulty, 0) + 1
    assert counts == {"easy": 15, "medium": 15, "hard": 30}  # 默认 25/25/50 配比
    assert len({p.id for p in s1}) == len(s1)  # 无重复
