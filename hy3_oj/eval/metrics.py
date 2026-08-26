"""评测指标：无偏 pass@k（组合估计）、难度分桶、收敛轮数统计。"""
from __future__ import annotations

import numpy as np


def pass_at_k(n: int, c: int, k: int) -> float:
    """无偏 pass@k 估计：1 - C(n-c, k) / C(n, k)。

    n: 总采样数；c: 通过数；k: 取值个数。参考 AlphaCode/OpenAI HumanEval 实现。
    """
    if n - c < k:
        return 1.0
    return float(1.0 - np.prod(1.0 - k / np.arange(n - c + 1, n + 1)))


def bucket_by_difficulty(records: list[dict]) -> dict[str, list[dict]]:
    """按难度分桶（easy/medium/hard），支撑难度分层分析（任务书 R8）。"""
    buckets: dict[str, list[dict]] = {}
    for r in records:
        buckets.setdefault(r.get("difficulty") or "unknown", []).append(r)
    return buckets
