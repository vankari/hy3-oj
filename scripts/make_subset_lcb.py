"""构建 LiveCodeBench 分层子集（任务书 R2 第二题集）。

从 livecodebench/code_generation_lite（release_v6）分层抽样落盘，
难度三桶均衡（easy/medium/hard 各 1/3），seed=42 可复现。

用法：python scripts/make_subset_lcb.py [--total 60] [--out data/subsets/subset_lcb_v1.jsonl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hy3_oj.data.loaders.livecodebench import iter_problems
from hy3_oj.data.subset import make_subset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=60)
    ap.add_argument("--out", default="data/subsets/subset_lcb_v1.jsonl")
    ap.add_argument("--version-tag", default="release_v6")
    args = ap.parse_args()

    print("流式加载 LCB（约 880 题，几分钟）...")
    problems = list(iter_problems(args.version_tag))
    print(f"有效题目 {len(problems)}")

    ratio = {"easy": 1 / 3, "medium": 1 / 3, "hard": 1 / 3}
    subset = make_subset(problems, total=args.total, seed=42, ratio=ratio)

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in subset:
            f.write(p.model_dump_json() + "\n")

    counts = {b: sum(1 for p in subset if p.difficulty == b) for b in ("easy", "medium", "hard")}
    functional = sum(1 for p in subset if "call-based" in p.statement)
    manifest = {
        "source": f"livecodebench/code_generation_lite ({args.version_tag})",
        "construction": "按 LCB difficulty 三桶均衡分层 + seed=42 随机抽样",
        "difficulty_basis": "LCB 官方 difficulty 标注（easy/medium/hard）",
        "total": len(subset),
        "buckets": counts,
        "call_based": functional,
        "seed": 42,
    }
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {path}：{counts}，其中 call-based {functional} 题")


if __name__ == "__main__":
    main()
