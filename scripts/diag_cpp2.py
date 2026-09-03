"""看 C++ 兜底触发后的完整状态序列与判题结果。"""
import json
from pathlib import Path

safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in "atcoder:arc181_c")
tf = Path("runs/trace") / f"{safe}.jsonl"
for line in tf.read_text(encoding="utf-8").splitlines():
    e = json.loads(line)
    s = e.get("state")
    if s == "JUDGED":
        v = e.get("verdicts") or []
        print(f"JUDGED round={e.get('round')} cand={e.get('cand')} passed={e.get('passed')} n={len(v)} sample={v[:5]}")
    elif s == "CPP_FALLBACK":
        print("CPP_FALLBACK", e.get("k"), e.get("warn", ""))
    elif s in ("REFINED", "REFLECTED"):
        print(s, "round=", e.get("round"), str(e.get("warn") or e.get("cause") or e.get("new_tags"))[:80])
