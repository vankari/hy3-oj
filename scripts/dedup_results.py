"""工具：结果文件去重（同名 problem_id 取最后一条），输出干净文件并统计。

用法：python scripts/dedup_results.py runs/closed_loop_lcb60_v7.jsonl
"""
from __future__ import annotations

import json
import sys

path = sys.argv[1]
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
merged: dict[str, dict] = {}
for r in recs:
    merged[r["problem_id"]] = r  # 后覆盖前
clean = list(merged.values())

out = path.replace(".jsonl", "_dedup.jsonl")
with open(out, "w", encoding="utf-8") as f:
    for r in clean:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(clean)
p = sum(1 for r in clean if r["passed"])
print(f"raw={len(recs)} dedup={n} passed={p} ({p/n:.1%}) -> {out}")
by_diff: dict[str, list] = {}
for r in clean:
    by_diff.setdefault(r.get("difficulty") or "?", []).append(r)
for d, rs in sorted(by_diff.items()):
    dp = sum(1 for r in rs if r["passed"])
    print(f"  {d}: {dp}/{len(rs)} = {dp/len(rs):.1%}")
