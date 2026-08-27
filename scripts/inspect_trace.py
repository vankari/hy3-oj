"""工具：查看某题闭环轨迹摘要（判题轮次 + 反思记录）。

用法：python scripts/inspect_trace.py "runs/trace/1149_B. Three Religions.jsonl"
"""
from __future__ import annotations

import json
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(line)
    s = e.get("state")
    if s == "JUDGED":
        print(f"[JUDGED] round={e['round']} passed={e['passed']} verdicts={e['verdicts'][:6]}{'...' if len(e['verdicts']) > 6 else ''}")
    elif s == "REFLECTED":
        print(f"[REFLECTED] round={e.get('round')} cause={e.get('cause')} diag={str(e.get('diagnosis'))[:120]}")
    elif s == "PLANNED" and "plan" in e:
        print(f"[PLANNED] tags={e['plan'].get('algorithm_tags')} approach_n={len(e['plan'].get('approach', []))}")
    elif s in ("GENERATED", "LOCAL_TESTED"):
        print(f"[{s}] { {k: v for k, v in e.items() if k != 'state'} }")
