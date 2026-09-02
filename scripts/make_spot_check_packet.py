"""生成人工抽检证据包：候选题的 Reviewer 指控 + 被审代码，供逐题核验（任务书 R7/R9）。"""
from __future__ import annotations

import json

CHECKS = "runs/review_mid100.spot_check.json"
REVIEWS = "runs/review_mid100.jsonl"
SOLUTIONS = "runs/closed_loop_mid100.jsonl"
OUT = "runs/spot_check_packet.md"


def load_jsonl(path: str) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def main() -> None:
    checks = json.load(open(CHECKS, encoding="utf-8"))
    reviews = {r["problem_id"]: r for r in load_jsonl(REVIEWS)}
    sols = {r["problem_id"]: r for r in load_jsonl(SOLUTIONS)}

    out = [
        "# 人工抽检证据包（mid100，14 候选）",
        "",
        "> 填写规范见 docs/人工抽检指南.md。每题给出：Reviewer 指控（fail 段证据）→ 被审代码全文。",
        "> 必要时按题号到 data/subsets/subset_mid100.jsonl 查题面原文。",
        "",
    ]
    for i, c in enumerate(checks, 1):
        pid = c["problem_id"]
        rev = reviews.get(pid, {})
        sol = sols.get(pid, {})
        out.append(
            f"## {i}. {pid}（error_step={c.get('error_step') or '-'} / "
            f"error_type={c.get('error_type') or '-'} / score={c['process_score']}）"
        )
        if c.get("lucky_pass_flags"):
            out.append(f"**蒙对信号（LLM 已确认）**：`{c['lucky_pass_flags']}`")
            out.append("")
        out.append("**Reviewer 逐步判定（fail 段证据）**：")
        out.append("")
        for sv in rev.get("step_verdicts", []):
            if not sv["passed"]:
                out.append(f"- **[{sv['step']}]** {sv['evidence']}")
        out.append("")
        out.append("**被审代码**：")
        out.append("")
        out.append("```python")
        out.append(sol.get("code", "(无)"))
        out.append("```")
        out.append("")

    text = "\n".join(out)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已生成 {OUT}：{len(checks)} 题，{len(text) // 1024} KB")


if __name__ == "__main__":
    main()
