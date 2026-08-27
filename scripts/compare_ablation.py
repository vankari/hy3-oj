"""工具：基线 vs 闭环消融对比（分桶、翻转题分析）。

用法：python scripts/compare_ablation.py runs/baseline_smoke.jsonl runs/closed_loop_smoke.jsonl
"""
from __future__ import annotations

import json
import sys


def load(path: str) -> dict[str, dict]:
    return {r["problem_id"]: r for r in (json.loads(l) for l in open(path, encoding="utf-8") if l.strip())}


def main() -> None:
    base = load(sys.argv[1])
    loop = load(sys.argv[2])
    ids = sorted(set(base) & set(loop))

    def rate(recs: dict, filt=None) -> str:
        sel = [recs[i] for i in ids if filt is None or filt(recs[i])]
        if not sel:
            return "-"
        p = sum(1 for r in sel if r["passed"])
        return f"{p}/{len(sel)} = {p / len(sel):.1%}"

    print("===== 基线 vs 闭环（同一 31 题）=====")
    print(f"总体   基线 {rate(base):>18}  闭环 {rate(loop):>18}")
    for d in ("easy", "medium", "hard"):
        f = lambda r, d=d: r.get("difficulty") == d  # noqa: E731
        print(f"{d:<7} 基线 {rate(base, f):>18}  闭环 {rate(loop, f):>18}")

    fixed = [i for i in ids if not base[i]["passed"] and loop[i]["passed"]]
    broken = [i for i in ids if base[i]["passed"] and not loop[i]["passed"]]
    print(f"\n闭环修复（基线错→闭环对）{len(fixed)} 题: {fixed}")
    print(f"闭环回退（基线对→闭环错）{len(broken)} 题: {broken}")

    rounds = [loop[i]["rounds"] for i in ids if loop[i]["passed"] and "rounds" in loop[i]]
    repaired = [loop[i]["rounds"] for i in ids if loop[i]["passed"] and loop[i].get("rounds", 0) > 0]
    if rounds:
        print(f"\n通过题平均轮数 {sum(rounds) / len(rounds):.2f}；经反思修复通过的题 {len(repaired)} 个: "
              f"{[i for i in ids if loop[i]['passed'] and loop[i].get('rounds', 0) > 0]}")


if __name__ == "__main__":
    main()
