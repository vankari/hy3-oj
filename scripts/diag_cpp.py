"""诊断 C++ 兜底为何 0 救回：看触发题的 C++ 代码与判题 verdict。"""
import json
from collections import Counter
from pathlib import Path

recs = {r["problem_id"]: r for r in (json.loads(l) for l in open("runs/closed_loop_lcb60_v9.jsonl", encoding="utf-8") if l.strip())}
fired = ["atcoder:arc181_c", "atcoder:arc190_d", "atcoder:abc389_g", "atcoder:abc363_e",
         "atcoder:abc306_e", "atcoder:abc396_e", "atcoder:arc183_c"]

for pid in fired[:3]:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in pid)
    tf = Path("runs/trace") / f"{safe}.jsonl"
    print(f"===== {pid} =====")
    if not tf.exists():
        print("  NO TRACE")
        continue
    events = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines()]
    cpp_idx = next(i for i, e in enumerate(events) if e.get("state") == "CPP_FALLBACK")
    after = [e for e in events[cpp_idx:] if e.get("state") == "JUDGED"]
    if after:
        c = Counter(after[0].get("verdicts") or [])
        print("  C++ 判题 verdicts:", dict(c.most_common()))
    print("  FINAL code head 300:")
    fin = next((e for e in events if e.get("state") == "FINAL"), None)
    if fin:
        print("   ", fin["code"][:300].replace("\n", "\\n"))
