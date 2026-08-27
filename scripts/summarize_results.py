"""工具：汇总基线/评测 jsonl 结果（pass@1、分桶、失败类型分布）。

用法：python scripts/summarize_results.py runs/baseline_smoke.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter


def main() -> None:
    path = sys.argv[1]
    recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    n = len(recs)
    p = sum(1 for r in recs if r.get("passed"))
    print(f"records: {n}  pass@1: {p}/{n} = {p / n:.1%}")
    print("verdicts:", dict(Counter(r.get("first_fail") or ("PASS" if r.get("passed") else "ERR") for r in recs)))
    by_diff: dict[str, list[dict]] = {}
    for r in recs:
        by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
    for d, rs in sorted(by_diff.items()):
        dp = sum(1 for r in rs if r.get("passed"))
        print(f"  {d}: {dp}/{len(rs)} = {dp / len(rs):.1%}")


if __name__ == "__main__":
    main()
