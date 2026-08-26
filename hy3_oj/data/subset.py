"""难度分层抽样（任务书 R2：说明来源、构造方式与分层依据）。

按 difficulty 三桶（easy/medium/hard）分层 + 固定 seed 抽样，
落盘 data/subsets/subset_v{n}.jsonl 保证可复现；同目录生成 manifest 说明。
"""
from __future__ import annotations

import json
import random
from collections.abc import Iterable
from pathlib import Path

from hy3_oj.core.schemas import Problem

BUCKETS = ("easy", "medium", "hard")

# 默认配比：hard 占一半以覆盖高难度区间（任务书 R2 要求覆盖基础→高难度）
DEFAULT_RATIO = {"easy": 0.25, "medium": 0.25, "hard": 0.50}


def make_subset(
    problems: Iterable[Problem],
    total: int = 300,
    seed: int = 42,
    ratio: dict[str, float] | None = None,
) -> list[Problem]:
    """分层抽样：每桶按 ratio 配额，桶内 seed 随机。"""
    ratio = ratio or DEFAULT_RATIO
    by_bucket: dict[str, list[Problem]] = {b: [] for b in BUCKETS}
    for p in problems:
        bucket = p.difficulty if p.difficulty in BUCKETS else "hard"
        by_bucket[bucket].append(p)

    rng = random.Random(seed)
    subset: list[Problem] = []
    for bucket, probs in by_bucket.items():
        quota = min(len(probs), round(total * ratio.get(bucket, 0.0)))
        subset.extend(rng.sample(probs, quota) if quota else [])
    rng.shuffle(subset)
    return subset


def save_subset(subset: list[Problem], path: str | Path, seed: int, source_desc: str = "deepmind/code_contests train") -> Path:
    """落盘 jsonl + manifest（来源/构造方式/分层依据，任务书 R2 说明材料）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in subset:
            f.write(p.model_dump_json() + "\n")

    counts = {b: sum(1 for p in subset if p.difficulty == b) for b in BUCKETS}
    manifest = {
        "source": source_desc,
        "construction": f"按 difficulty 三桶分层 + seed={seed} 随机抽样",
        "difficulty_basis": "CodeContests difficulty 枚举映射（1→easy, 2→medium, 3~5→hard）；未知时用 cf_rating 兜底（<1400 easy, <1900 medium）",
        "total": len(subset),
        "buckets": counts,
        "seed": seed,
    }
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_subset(path: str | Path) -> list[Problem]:
    """读取落盘子集（可复现评测的输入）。"""
    with open(path, encoding="utf-8") as f:
        return [Problem.model_validate_json(line) for line in f if line.strip()]
