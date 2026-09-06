"""挑选 demo 展示题：从已有评测结果中，每个难度各选一题**已成功**的题。

录制 demo 必须用已验证通过的题（避免录制时翻车）。优先选：
1. 修复轮数少（rounds=0 表示一次通过，速度快、画面干净）
2. 判题点数适中（太少显得单薄，太多耗时）

输出 demo_problems.md 清单 + 可直接复制的命令。
"""
from __future__ import annotations

import json
from pathlib import Path

SOURCES = {
    "LiveCodeBench": ("runs/closed_loop_lcb60_v10.jsonl", "data/subsets/subset_lcb_v1.jsonl"),
    "CodeContests": ("runs/closed_loop_mid100_v11.jsonl", "data/subsets/subset_mid100.jsonl"),
}


def pick(results_path: str, subset_path: str) -> dict[str, dict]:
    recs = [json.loads(l) for l in open(results_path, encoding="utf-8") if l.strip()]
    ok = [r for r in recs if r.get("passed")]
    by_diff: dict[str, list] = {}
    for r in ok:
        by_diff.setdefault(r.get("difficulty") or "?", []).append(r)
    picked = {}
    for d, rs in by_diff.items():
        # 优先 rounds 少，其次判题点数适中
        best = sorted(rs, key=lambda r: (r.get("rounds") or 99, -len(r.get("verdicts") or [])))
        picked[d] = best[0]
    return picked


def main() -> None:
    lines = ["# Demo 展示题清单（已验证通过，录制用）\n",
             "> 由 `scripts/pick_demo_problems.py` 从已有评测结果中挑选：每个难度一题，",
             "优先选一次通过（rounds=0）的题，保证录制时稳定复现。\n"]
    all_picks = {}
    for name, (res_p, sub_p) in SOURCES.items():
        if not Path(res_p).exists():
            continue
        picked = pick(res_p, sub_p)
        all_picks[name] = (picked, sub_p)
        lines.append(f"\n## {name}\n")
        lines.append(f"\n来源子集：`{sub_p}`\n")
        lines.append("\n| 难度 | 题号 | 修复轮数 | 判题点数 | 演示命令 |")
        lines.append("|---|---|---|---|---|")
        for d in ("easy", "medium", "hard"):
            r = picked.get(d)
            if not r:
                continue
            pid = r["problem_id"]
            cmd = f"python scripts/demo_solve.py --subset {sub_p} --id \"{pid}\""
            lines.append(f"| {d} | `{pid}` | {r.get('rounds')} | {len(r.get('verdicts') or [])} | `{cmd}` |")
    Path("docs/demo_problems.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
