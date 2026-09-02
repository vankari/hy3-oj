"""统计 v8 最终结果（不依赖命令行输出编码）。"""
import json

p = "runs/closed_loop_lcb60_v8.jsonl"
recs = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
n = len(recs)
passed = [r for r in recs if r.get("passed")]
print(f"total={n} passed={len(passed)} rate={len(passed)/n:.1%}")

bd: dict[str, list] = {}
for r in recs:
    bd.setdefault(r.get("difficulty") or "?", []).append(r)
for d, rs in sorted(bd.items()):
    dp = sum(1 for r in rs if r.get("passed"))
    print(f"  {d}: {dp}/{len(rs)} = {dp/len(rs):.1%}")

print("failed:", [r["problem_id"] for r in recs if not r.get("passed")])
