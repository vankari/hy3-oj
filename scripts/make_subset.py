"""入口：构建评测子集（D2）。

用法：
    python scripts/make_subset.py [--total 300] [--scan-limit 3000] [--out data/subsets/subset_v1.jsonl]

HF 直连失败时先执行：$env:HF_ENDPOINT="https://hf-mirror.com"
"""
from __future__ import annotations

import argparse

from hy3_oj.data.loaders.codecontests import iter_problems
from hy3_oj.data.subset import make_subset, save_subset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=300)
    ap.add_argument("--scan-limit", type=int, default=3000, help="流式扫描的最大题数（越大桶内候选越足）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/subsets/subset_v1.jsonl")
    args = ap.parse_args()

    print(f"流式扫描 CodeContests（scan_limit={args.scan_limit}）...")
    candidates = list(iter_problems(split="train", limit=args.scan_limit))
    print(f"合法候选 {len(candidates)} 题")

    subset = make_subset(candidates, total=args.total, seed=args.seed)
    path = save_subset(subset, args.out, seed=args.seed)

    buckets = {}
    for p in subset:
        buckets[p.difficulty] = buckets.get(p.difficulty, 0) + 1
    print(f"子集落盘 {path}（{len(subset)} 题）：{buckets}")
    print(f"manifest: {path.with_suffix('.manifest.json')}")


if __name__ == "__main__":
    main()
