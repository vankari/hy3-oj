"""统计 CodeContests mid100 难度构成、失分题与失败类型。"""
import json
from collections import Counter
from pathlib import Path

probs = {p.id: p for p in __import__(
    "hy3_oj.data.subset", fromlist=["load_subset"]).load_subset("data/subsets/subset_mid100.jsonl")}
recs = [json.loads(l) for l in open("runs/closed_loop_mid100_v11.jsonl", encoding="utf-8") if l.strip()]

print(f"总题数 {len(recs)}，子集题数 {len(probs)}")
bd: dict[str, list] = {}
for r in recs:
    bd.setdefault(r.get("difficulty") or "?", []).append(r)
print("\n难度构成与通过率：")
for d, rs in sorted(bd.items()):
    dp = sum(1 for r in rs if r.get("passed"))
    print(f"  {d}: {len(rs)} 题，通过 {dp} ({dp/len(rs):.1%})，失败 {len(rs)-dp}")

print("\n失分题（按难度）：")
for d, rs in sorted(bd.items()):
    fails = [r["problem_id"] for r in rs if not r.get("passed")]
    if fails:
        print(f"  {d} ({len(fails)}): {fails}")

# 失败类型
print("\n失败 verdict（最后一轮）：")
c = Counter()
for r in recs:
    if r.get("passed"):
        continue
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in r["problem_id"])
    tf = Path("runs/trace") / f"{safe}.jsonl"
    if not tf.exists():
        continue
    last = None
    for line in tf.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("state") == "JUDGED":
            last = e
    if last and last.get("verdicts"):
        c.update(Counter(last["verdicts"]))
print(" ", dict(c.most_common()))
