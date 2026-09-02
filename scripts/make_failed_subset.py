"""工具：从评测结果中筛出失败题，生成重跑子集（验证改进效果，省额度）。

用法：python scripts/make_failed_subset.py runs/closed_loop_lcb60.jsonl data/subsets/lcb60.jsonl data/subsets/lcb60_failed.jsonl
"""
from __future__ import annotations

import json
import sys

from hy3_oj.core.schemas import Problem

results = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
failed_ids = {r["problem_id"] for r in results if not r.get("passed")}
problems = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
failed_problems = [p for p in problems if p.get("id") in failed_ids or p.get("name") in failed_ids]

with open(sys.argv[3], "w", encoding="utf-8") as f:
    for p in failed_problems:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
print(f"失败题 {len(failed_ids)}，匹配到子集 {len(failed_problems)} → {sys.argv[3]}")
missing = failed_ids - {p.get("id") or p.get("name") for p in failed_problems}
if missing:
    print("未匹配（检查 id 字段）:", missing)
