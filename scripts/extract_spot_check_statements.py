"""抽取 14 条抽检候选的题面（供人工/AI 抽检核验）。"""
from __future__ import annotations

import json

IDS = [
    "1330_D. Dreamoon Likes Sequences",
    "benny-and-the-broken-odometer",
    "1391_C. Cyclic Permutations ",
    "343_B. Alternating Current",
    "358_B. Dima and Text Messages",
    "p01811 ABC Gene",
    "p02939 AtCoder Grand Contest 037 - Dividing a String",
    "anagrams-1",
    "1397_B. Power Sequence",
    "1159_A. A pile of stones",
    "1062_D. Fun with Integers",
    "p03254 AtCoder Grand Contest 027 - Candy Distribution Again",
    "start01",
    "513_A. Game",
]

problems = {}
with open("data/subsets/subset_mid100.jsonl", encoding="utf-8") as f:
    for line in f:
        p = json.loads(line)
        if p["id"] in IDS:
            problems[p["id"]] = p

with open("runs/spot_check_statements.md", "w", encoding="utf-8") as out:
    for pid in IDS:
        p = problems.get(pid)
        if not p:
            out.write(f"## {pid}\n(未找到)\n\n")
            continue
        out.write(f"## {pid}\n\n")
        out.write(f"难度: {p.get('difficulty')} | tags: {p.get('tags')}\n\n")
        out.write(p["statement"][:3500])
        out.write("\n\n样例:\n")
        for s in p.get("samples", [])[:3]:
            out.write(f"- 输入: {s['input'][:200]!r}\n  输出: {(s.get('expected_output') or '')[:200]!r}\n")
        out.write("\n---\n\n")
print("done", len(problems))
