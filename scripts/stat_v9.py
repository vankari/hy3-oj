"""统计 v9 结果 + C++ 兜底触发情况。"""
import json
from pathlib import Path

recs = [json.loads(l) for l in open("runs/closed_loop_lcb60_v9.jsonl", encoding="utf-8") if l.strip()]
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

# C++ 兜底触发与成效
cpp_fired, cpp_rescued = [], []
for r in recs:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in r["problem_id"])
    tf = Path("runs/trace") / f"{safe}.jsonl"
    if not tf.exists():
        continue
    fired = False
    for line in tf.read_text(encoding="utf-8").splitlines():
        if '"CPP_FALLBACK"' in line:
            fired = True
    if fired:
        cpp_fired.append(r["problem_id"])
        if r.get("passed"):
            cpp_rescued.append(r["problem_id"])
print(f"C++ 兜底触发 {len(cpp_fired)} 题，其中救回 {len(cpp_rescued)} 题")
print("  fired:", cpp_fired)
print("  rescued:", cpp_rescued)
