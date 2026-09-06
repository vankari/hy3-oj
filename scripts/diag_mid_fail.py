"""诊断 mid100 失败题：末轮 verdict 分布 + 是否触发 C++ 兜底/重规划。

注意：题号→轨迹文件名必须用 pipeline._safe_name（正则连续替换），
逐字符替换会生成双下划线而找不到文件（踩过的坑）。
"""
import json
import re
from collections import Counter
from pathlib import Path


def safe_name(pid: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", pid)  # 与 SolvePipeline._safe_name 一致


TARGETS = {
    "easy": ["513_A. Game"],
    "medium": ["175_B. Plane of Tanks: Pro", "378_C. Maze"],
    "hard": ["494_D. Birthday", "354_B. Game with Strings", "737_C. Subordinates",
             "543_C. Remembering Strings", "105_C. Item World", "p00993 Numbers",
             "mystery-10", "709_D. Recover the String", "1349_D. Slime and Biscuits",
             "809_D. Hitchhiking in the Baltic States", "1394_D. Boboniu and Jianghu",
             "p01288 Marked Ancestor", "p01290 Queen's Case", "p01856 Typhoon",
             "1251_E1. Voting (Easy Version)"],
}

for diff, pids in TARGETS.items():
    print(f"\n{'='*64}\n{diff}（{len(pids)} 题）\n{'='*64}")
    for pid in pids:
        tf = Path("runs/trace") / f"{safe_name(pid)}.jsonl"
        if not tf.exists():
            print(f"  {pid}: NO TRACE")
            continue
        events = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines()]
        judged = [e for e in events if e.get("state") == "JUDGED"]
        if not judged:
            print(f"  {pid}: 无判题事件")
            continue
        last = judged[-1]
        v = Counter(last.get("verdicts") or [])
        n = sum(v.values())
        ac = v.get("AC", 0)
        cpp = any(e.get("state") == "CPP_FALLBACK" for e in events)
        refined = sum(1 for e in events if e.get("state") == "REFINED")
        # 控制台为 GBK，勿用 emoji（会 UnicodeEncodeError）
        tag = "[NEAR]" if ac / n >= 0.5 else ("[ALL-FAIL]" if ac == 0 else "[PARTIAL]")
        print(f"  {pid}")
        print(f"    AC {ac}/{n} ({ac/n:.0%}) {tag} | WA={v.get('WA',0)} RE={v.get('RE',0)} "
              f"TLE={v.get('TLE',0)} | 轮次={last.get('round')} C++={'是' if cpp else '否'} 重规划={refined}")
