"""报告生成（D11：正式集难度分层结果）。

核心产出（任务书 R8）：按 easy/medium/hard 分层的
**答案正确率 / 过程正确率 / 五段逐段正确率 / 错误类型分布 / 蒙对定罪数**，
以及"能力临界点"（相邻难度档的正确率跌幅）。

TODO(D12): 消融表格 / 成本-效果帕累托曲线 / 失败案例导出。
"""
from __future__ import annotations

from collections import Counter

STEPS = ["题意理解", "算法选型", "复杂度论证", "边界处理", "实现一致性"]
BUCKETS = ["easy", "medium", "hard"]
PROCESS_OK_THRESHOLD = 0.8  # 与 run_review.py 口径一致：process_score ≥ 0.8 视为过程成立


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def summarize_by_difficulty(
    solve_records: list[dict],
    review_records: list[dict],
    threshold: float = PROCESS_OK_THRESHOLD,
) -> dict:
    """把闭环结果 + 过程评估结果按难度分桶汇总。"""
    review_by_id = {r["problem_id"]: r for r in review_records}
    rows: dict[str, list[tuple[dict, dict | None]]] = {b: [] for b in BUCKETS}
    for s in solve_records:
        b = s.get("difficulty") or "unknown"
        rows.setdefault(b, []).append((s, review_by_id.get(s["problem_id"])))

    def agg(pairs: list[tuple[dict, dict | None]]) -> dict:
        n = len(pairs)
        if not n:
            return {"n": 0}
        answered = sum(1 for s, _ in pairs if s.get("passed"))
        # 无审查记录或审查失败（缺 process_score）的题不计入过程类指标分母
        reviewed = [(s, r) for s, r in pairs if r and "process_score" in r]
        rn = len(reviewed)
        process_ok = sum(1 for _, r in reviewed if r["process_score"] >= threshold)
        no_fail_step = sum(1 for _, r in reviewed
                           if not any(sv["passed"] is False for sv in r.get("step_verdicts", [])))
        lucky = sum(1 for _, r in reviewed if r.get("answer_passed") and r.get("lucky_pass_flags"))
        suspects = sum(1 for _, r in reviewed
                       if not r.get("lucky_pass_flags")
                       and (r.get("error_step") or r["process_score"] < threshold))
        rounds = [s.get("rounds") for s, _ in pairs if s.get("passed") and s.get("rounds") is not None]
        scores = [r["process_score"] for _, r in reviewed]
        step_stat = {st: [0, 0] for st in STEPS}  # [pass, total]
        for _, r in reviewed:
            for sv in r.get("step_verdicts", []):
                st = sv.get("step")
                if st in step_stat:
                    step_stat[st][1] += 1
                    if sv.get("passed"):
                        step_stat[st][0] += 1
        err_types = Counter(r["error_type"] for _, r in reviewed if r.get("error_type"))
        answer_passed_n = sum(1 for _, r in reviewed if r.get("answer_passed"))
        return {
            "n": n,
            "reviewed": rn,
            "answer_passed": answered,
            "answer_acc": _rate(answered, n),
            "process_ok": process_ok,
            "process_acc": _rate(process_ok, rn),
            "no_fail_step": no_fail_step,
            "no_fail_step_rate": _rate(no_fail_step, rn),
            "lucky_convictions": lucky,
            "lucky_rate_of_ac": _rate(lucky, answer_passed_n),
            "process_suspects": suspects,
            "avg_rounds_of_passed": (sum(rounds) / len(rounds)) if rounds else 0.0,
            "avg_process_score": (sum(scores) / len(scores)) if scores else 0.0,
            "step_pass": {st: {"passed": v[0], "total": v[1], "rate": _rate(v[0], v[1])}
                          for st, v in step_stat.items()},
            "error_types": dict(err_types.most_common()),
        }

    buckets = {b: agg(pairs) for b, pairs in rows.items() if pairs}
    all_pairs = [p for pairs in rows.values() for p in pairs]
    overall = agg(all_pairs)

    # 能力临界点：相邻档答案正确率最大跌幅（任务书 R8：指出表现明显下降的难度区间）
    drops = []
    for a, b in zip(BUCKETS, BUCKETS[1:]):
        ra = buckets.get(a, {}).get("answer_acc")
        rb = buckets.get(b, {}).get("answer_acc")
        if ra is not None and rb is not None and buckets.get(a, {}).get("n") and buckets.get(b, {}).get("n"):
            drops.append({"from": a, "to": b, "answer_drop_pt": (ra - rb) * 100,
                          "from_acc": ra, "to_acc": rb})
    return {
        "overall": overall,
        "buckets": buckets,
        "difficulty_drops": sorted(drops, key=lambda d: -d["answer_drop_pt"]),
        "threshold": threshold,
    }


def render_markdown(summary: dict, meta: dict | None = None) -> str:
    """渲染分层结果 markdown（可直接进技术报告）。"""
    meta = meta or {}
    overall = summary["overall"]
    buckets = summary["buckets"]
    lines: list[str] = []
    lines.append("# 正式集评测报告（任务书 R8 分层结果）\n")
    if meta:
        lines.append("> " + "｜".join(f"{k}：{v}" for k, v in meta.items()) + "\n")

    def pct(x: float) -> str:
        return f"{x:.1%}"

    # 主表：答案正确率 vs 过程正确率（逐难度）
    lines.append("\n## 一、分层主结果（答案正确率 / 过程正确率）\n")
    lines.append("| 难度 | 题数 | 答案正确率 | 过程正确率 | 无 fail 段占比 | 蒙对定罪（占 AC） | 过程存疑 | 平均收敛轮数(通过题) | 平均分 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for b in BUCKETS:
        s = buckets.get(b)
        if not s or not s.get("n"):
            continue
        lines.append(
            f"| {b} | {s['n']} | **{pct(s['answer_acc'])}** ({s['answer_passed']}/{s['n']}) | "
            f"**{pct(s['process_acc'])}** ({s['process_ok']}/{s['reviewed']}) | "
            f"{pct(s['no_fail_step_rate'])} | {s['lucky_convictions']} ({pct(s['lucky_rate_of_ac'])}) | "
            f"{s['process_suspects']} | {s['avg_rounds_of_passed']:.2f} | {s['avg_process_score']:.2f} |"
        )
    lines.append(
        f"| **总体** | {overall['n']} | **{pct(overall['answer_acc'])}** ({overall['answer_passed']}/{overall['n']}) | "
        f"**{pct(overall['process_acc'])}** ({overall['process_ok']}/{overall['reviewed']}) | "
        f"{pct(overall['no_fail_step_rate'])} | {overall['lucky_convictions']} ({pct(overall['lucky_rate_of_ac'])}) | "
        f"{overall['process_suspects']} | {overall['avg_rounds_of_passed']:.2f} | {overall['avg_process_score']:.2f} |"
    )
    lines.append(
        f"\n- 过程成立口径：process_score ≥ {summary['threshold']}（与 `run_review.py` 一致）；"
        "蒙对定罪只采信机器验证证据（行为探针）或规则+LLM 双确认，见 `docs/process_evaluation_report.md` §二。"
    )

    # 逐段（五段式）正确率
    lines.append("\n## 二、五段式逐段正确率（逐过程正确率，任务书 R3/R4）\n")
    lines.append("| 难度 | " + " | ".join(STEPS) + " |")
    lines.append("|---|" + "---|" * len(STEPS))
    for b in BUCKETS:
        s = buckets.get(b)
        if not s or not s.get("n"):
            continue
        cells = []
        for st in STEPS:
            v = s["step_pass"].get(st, {"passed": 0, "total": 0, "rate": 0.0})
            cells.append(f"{pct(v['rate'])} ({v['passed']}/{v['total']})")
        lines.append(f"| {b} | " + " | ".join(cells) + " |")
    o_cells = []
    for st in STEPS:
        v = overall["step_pass"].get(st, {"passed": 0, "total": 0, "rate": 0.0})
        o_cells.append(f"{pct(v['rate'])} ({v['passed']}/{v['total']})")
    lines.append(f"| **总体** | " + " | ".join(o_cells) + " |")
    lines.append("\n（分母 = 该档已完成过程审查的题数；一段 fail 即代表该题过程在此步出现首个错误。）")

    # 错误类型分布
    lines.append("\n## 三、过程错误类型分布（任务书 R5）\n")
    types = sorted({t for s in buckets.values() for t in s.get("error_types", {})})
    if types:
        lines.append("| 错误类型 | " + " | ".join(b for b in BUCKETS if buckets.get(b)) + " | 合计 |")
        lines.append("|---|" + "---|" * (len([b for b in BUCKETS if buckets.get(b)]) + 1))
        for t in types:
            cells, tot = [], 0
            for b in BUCKETS:
                s = buckets.get(b)
                if not s:
                    continue
                c = s.get("error_types", {}).get(t, 0)
                tot += c
                cells.append(str(c))
            lines.append(f"| {t} | " + " | ".join(cells) + f" | {tot} |")
    else:
        lines.append("（暂无错误类型数据）")
    lines.append("\n注：语义层错误类型含一定误报倾向（mid100 抽检约 2~3 成），仅作趋势分析，不作定罪依据。")

    # 能力临界点
    lines.append("\n## 四、能力临界点（任务书 R8）\n")
    for d in summary["difficulty_drops"]:
        lines.append(f"- {d['from']} → {d['to']}：答案正确率 {pct(d['from_acc'])} → {pct(d['to_acc'])}"
                     f"（跌 {d['answer_drop_pt']:.1f}pt）")
    if not summary["difficulty_drops"]:
        lines.append("-（难度档不足，无法计算跌幅）")
    return "\n".join(lines) + "\n"
