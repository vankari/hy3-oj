"""工具：失败类型分布诊断（锁定 90+ 改造点）。

用法：python scripts/diagnose_failures.py runs/closed_loop_lcb60.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter

recs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
n = len(recs)
passed = [r for r in recs if r.get("passed")]
failed = [r for r in recs if not r.get("passed")]
print(f"total={n} passed={len(passed)} ({len(passed)/n:.1%}) failed={len(failed)}")

# 失败类型（verdicts 里的首个非 AC，或 error）
c = Counter()
for r in failed:
    if r.get("error"):
        c["ERROR:" + r["error"][:30]] += 1
        continue
    v = r.get("verdicts") or []
    fail = next((x for x in v if x != "AC"), None)
    c[fail or ("rounds=" + str(r.get("rounds")))] += 1
print("失败类型分布:", dict(c))

# 分难度失败率
bd = {}
for r in recs:
    bd.setdefault(r.get("difficulty") or "?", []).append(r)
for d, rs in sorted(bd.items()):
    p = sum(1 for x in rs if x.get("passed"))
    print(f"  {d}: {p}/{len(rs)} = {p/len(rs):.1%}")

# 失败题按轮数分布（判断反思是否有效）
rounds_c = Counter(r.get("rounds") for r in failed)
print("失败题轮数分布:", dict(sorted(rounds_c.items(), key=lambda x: str(x[0]))))
print("失败题列表:", [r["problem_id"] for r in failed])
