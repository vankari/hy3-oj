"""入口：正式集评测（D11）——闭环解题 → 过程评估 → 难度分层报告。

用法（正式集 300 题，默认 subset_v1：easy 75 / medium 75 / hard 150）：

    python scripts/run_eval.py \
        --subset data/subsets/subset_v1.jsonl \
        --out-solve runs/closed_loop_v3_300.jsonl \
        --out-review runs/review_v3_300.jsonl \
        --report docs/formal_eval_report.md

三阶段解耦，任一阶段中断后可原样重跑续跑（resume 按 problem_id 去重）：
  1. solve：闭环解题（慢、耗 token）   --skip-solve 跳过
  2. review：Reviewer 过程评估（含 AC 解行为探针）  --skip-review 跳过
  3. report：按 easy/medium/hard 汇总（答案正确率 / 过程正确率 / 五段逐段 / 错误类型）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from hy3_oj.core.config import load_config
from hy3_oj.core.pipeline import SolvePipeline
from hy3_oj.core.schemas import ProcessErrorType, ProcessReview, ReviewStep
from hy3_oj.data.subset import load_subset
from hy3_oj.eval import runner
from hy3_oj.eval.process_eval import false_positive_candidates
from hy3_oj.eval.report import BUCKETS, render_markdown, summarize_by_difficulty
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor

METERING = Path("runs/metering.jsonl")


def _metering_offset() -> int:
    """返回当前计量日志行数（用于只统计本次评测的 token 增量）。"""
    if not METERING.exists():
        return 0
    return sum(1 for line in METERING.read_text(encoding="utf-8").splitlines() if line.strip())


def _token_delta(offset: int) -> dict:
    """聚合 offset 之后新增的计量事件（按 mode 汇总）。"""
    if not METERING.exists():
        return {}
    new_lines = [l for l in METERING.read_text(encoding="utf-8").splitlines()[offset:] if l.strip()]
    by_mode: dict[str, dict] = {}
    for line in new_lines:
        e = json.loads(line)
        b = by_mode.setdefault(e["mode"], {"calls": 0, "prompt": 0, "completion": 0, "reasoning": 0, "total": 0})
        b["calls"] += 1
        b["prompt"] += e["prompt_tokens"]
        b["completion"] += e["completion_tokens"]
        b["reasoning"] += e["reasoning_tokens"]
        b["total"] += e["total_tokens"]
    return by_mode


def _write_spot_check(review_records: list[dict], review_path: str) -> Path | None:
    """导出蒙对定罪候选（供人工抽检填 human_verdict，任务书 R7）。"""
    reviews = []
    for r in review_records:
        if not r.get("answer_passed"):
            continue
        reviews.append((r["problem_id"], ProcessReview(
            error_step=ReviewStep(r["error_step"]) if r.get("error_step") else None,
            error_type=ProcessErrorType(r["error_type"]) if r.get("error_type") else None,
            lucky_pass_flags=r.get("lucky_pass_flags") or [],
            process_score=r.get("process_score", 0.0),
        )))
    candidates = false_positive_candidates(reviews)
    path = Path(review_path).with_suffix(".spot_check.json")
    if path.exists():  # 不覆盖已填的抽检记录
        return path
    path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    return path if candidates else None


def _print_summary(summary: dict) -> None:
    overall = summary["overall"]
    print(f"\n===== 正式集分层结果（{overall['n']} 题，已审查 {overall['reviewed']}）=====")
    print(f"总体 答案正确率 {overall['answer_acc']:.1%}（{overall['answer_passed']}/{overall['n']}）｜"
          f"过程正确率 {overall['process_acc']:.1%}（{overall['process_ok']}/{overall['reviewed']}）")
    print(f"{'难度':<8}{'题数':>6}{'答案正确率':>12}{'过程正确率':>12}{'逐段(题意/算法/复杂度/边界/实现)':>40}")
    for b in BUCKETS:
        s = summary["buckets"].get(b)
        if not s or not s.get("n"):
            continue
        steps = "/".join(f"{s['step_pass'][st]['rate']:.0%}" for st in
                         ["题意理解", "算法选型", "复杂度论证", "边界处理", "实现一致性"])
        print(f"{b:<8}{s['n']:>6}{s['answer_acc']:>12.1%}{s['process_acc']:>12.1%}{steps:>40}")
    et = Counter()
    for s in summary["buckets"].values():
        et.update(s.get("error_types", {}))
    if et:
        print("错误类型分布:", dict(et.most_common()))
    for d in summary["difficulty_drops"]:
        print(f"能力临界点 {d['from']}→{d['to']}: {d['from_acc']:.1%} → {d['to_acc']:.1%}"
              f"（跌 {d['answer_drop_pt']:.1f}pt）")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="data/subsets/subset_v1.jsonl")
    ap.add_argument("--out-solve", default="runs/closed_loop_v3_300.jsonl")
    ap.add_argument("--out-review", default="runs/review_v3_300.jsonl")
    ap.add_argument("--summary", default="runs/formal_eval_summary.json")
    ap.add_argument("--report", default="docs/formal_eval_report.md")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4, help="闭环并发（受容器池/额度约束）")
    ap.add_argument("--review-concurrency", type=int, default=6)
    ap.add_argument("--skip-solve", action="store_true")
    ap.add_argument("--skip-review", action="store_true")
    ap.add_argument("--no-resume", action="store_true", help="忽略已有结果，全量重跑")
    ap.add_argument("--tag", default="v3", help="实验标签（写入报告头部）")
    args = ap.parse_args()

    cfg = load_config()
    problems = load_subset(args.subset)
    if args.limit:
        problems = problems[: args.limit]
    resume = not args.no_resume
    t0 = time.time()
    offset = _metering_offset()

    solve_records = runner.load_jsonl(args.out_solve)
    if not args.skip_solve:
        pipeline = SolvePipeline(cfg)
        try:
            solve_records = await runner.run_subset(
                problems, pipeline, args.out_solve, concurrency=args.concurrency, resume=resume)
        finally:
            await pipeline.client.close()
            pipeline.executor.close()
    else:
        print(f"[solve] 跳过，复用 {args.out_solve}（{len(solve_records)} 条）")

    review_records = runner.load_jsonl(args.out_review)
    if not args.skip_review:
        client = Hy3Client(cfg)
        executor = DockerExecutor(cfg)
        try:
            review_records = await runner.run_reviews(
                problems, solve_records, cfg, args.out_review,
                concurrency=args.review_concurrency, resume=resume,
                client=client, executor=executor)
        finally:
            await client.close()
            executor.close()
    else:
        print(f"[review] 跳过，复用 {args.out_review}（{len(review_records)} 条）")

    summary = summarize_by_difficulty(solve_records, review_records)
    summary["meta"] = {
        "tag": args.tag,
        "subset": args.subset,
        "solve_out": args.out_solve,
        "review_out": args.out_review,
        "elapsed_min": round((time.time() - t0) / 60, 1),
        "tokens_this_run": _token_delta(offset),
    }
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_summary(summary)

    spot = _write_spot_check(review_records, args.out_review)
    if spot:
        print(f"[R7] 蒙对定罪候选已导出：{spot}（人工填 human_verdict 后算误报率）")

    counts = Counter(p.difficulty for p in problems)
    meta = {
        "标签": args.tag,
        "子集": f"{args.subset}（" + "/".join(f"{k} {v}" for k, v in sorted(counts.items())) + "）",
        "模型": f"hy3（{cfg['llm'].get('model')}）",
        "耗时": f"{summary['meta']['elapsed_min']} min",
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(summary, meta), encoding="utf-8")
    print(f"[report] {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
