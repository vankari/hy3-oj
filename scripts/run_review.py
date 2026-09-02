"""入口：过程评估（任务书核心 R3–R7）。

模式：
  --mode review       对闭环结果全量跑 Reviewer（五段式审查 + 蒙对检测）
  --mode inject       官方参考解注入 bug → 验证 Reviewer 定位准确率
  --mode fp           汇总误报率（需先人工填抽检记录 human_verdict）

用法：
  python scripts/run_review.py --mode review --subset data/subsets/subset_smoke.jsonl --solutions runs/closed_loop_v2.jsonl --out runs/review_smoke.jsonl
  python scripts/run_review.py --mode inject --subset data/subsets/subset_smoke.jsonl --out runs/inject_smoke.jsonl --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter
from pathlib import Path

from hy3_oj.agents import reviewer
from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Plan, Problem, Solution
from hy3_oj.data.subset import load_subset
from hy3_oj.eval.process_eval import (
    false_positive_candidates,
    false_positive_rate,
    inject_bug,
    localization_accuracy,
)
from hy3_oj.llm.client import Hy3Client


def _load_jsonl(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_plan_from_trace(trace_file: str) -> Plan | None:
    p = Path(trace_file) if trace_file else None
    if not p or not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("state") == "PLAN":
            return Plan(**e["plan"])
        if e.get("state") == "PLANNED" and "plan" in e:
            return Plan(**e["plan"])
    return None


async def mode_review(client, problems: list[Problem], solutions: dict, out: str, concurrency: int, cfg) -> None:
    from hy3_oj.sandbox.docker_executor import DockerExecutor

    executor = DockerExecutor(cfg)
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def one(p: Problem) -> None:
        rec = solutions.get(p.id)
        if not rec or not rec.get("code"):
            return
        plan = _load_plan_from_trace(rec.get("trace_file", ""))
        verdict_summary = "AC（全部测试点通过）" if rec.get("passed") else f"未通过（{rec.get('rounds', 0)} 轮修复后仍失败）"
        sol = Solution(code=rec["code"])
        async with sem:
            review = await reviewer.review(client, p, plan, sol, verdict_summary,
                                           executor=executor, answer_passed=bool(rec.get("passed")))
        out_rec = {
            "problem_id": p.id, "difficulty": p.difficulty, "answer_passed": rec.get("passed"),
            "process_score": review.process_score,
            "error_step": review.error_step.value if review.error_step else None,
            "error_type": review.error_type.value if review.error_type else None,
            "lucky_pass_flags": review.lucky_pass_flags,
            "step_verdicts": [{"step": sv.step.value, "passed": sv.passed, "evidence": sv.evidence[:100]} for sv in review.step_verdicts],
        }
        async with lock:
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            flag = " [蒙对?]" if out_rec["lucky_pass_flags"] else ""
            print(f"{p.id}: answer={'AC' if rec.get('passed') else 'FAIL'} process={review.process_score:.2f}{flag}")

    await asyncio.gather(*(one(p) for p in problems))

    # 汇总：答案正确率 vs 过程正确率（任务书 R8）
    recs = _load_jsonl(out)
    n = len(recs)
    if n:
        ac = sum(1 for r in recs if r["answer_passed"])
        process_ok = sum(1 for r in recs if r["process_score"] >= 0.8)
        lucky = [r for r in recs if r["answer_passed"] and r["process_score"] < 0.8]
        print(f"\n===== 过程评估汇总（{n} 题）=====")
        print(f"答案正确率 {ac}/{n} = {ac / n:.1%}；过程正确率 {process_ok}/{n} = {process_ok / n:.1%}")
        print(f"答案对但过程不成立 {len(lucky)} 题: {[r['problem_id'] for r in lucky]}")
        et = Counter(r["error_type"] for r in recs if r["error_type"])
        if et:
            print("错误类型分布:", dict(et))


async def mode_inject(client, problems: list[Problem], out: str, limit: int, concurrency: int) -> None:
    rng = random.Random(42)
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    tasks = []

    for p in problems:
        for ref in p.reference_solutions[:1]:
            injected = inject_bug(ref, rng)
            if not injected:
                continue
            buggy, gt_step, desc = injected
            tasks.append((p, ref, buggy, gt_step, desc))
        if len(tasks) >= limit:
            break
    tasks = tasks[:limit]
    print(f"成功注入 bug {len(tasks)} 例（ground truth 已知）")

    async def one(p: Problem, orig: str, buggy: str, gt_step, desc: str) -> None:
        async with sem:
            review = await reviewer.review(
                client, p, None, Solution(code=buggy),
                "该代码是官方正确参考解被注入恰好一处局部改动（单行内）后的版本，其余逻辑正确。"
                "请定位这处改动，并判定其归属的步骤段",
            )
        rec = {
            "problem_id": p.id, "injected_step": gt_step.value, "injected_desc": desc,
            "pred_step": review.error_step.value if review.error_step else None,
            "hit": review.error_step == gt_step,
            "process_score": review.process_score,
            "step_verdicts": [
                {"step": sv.step.value, "passed": sv.passed, "evidence": sv.evidence[:200]}
                for sv in review.step_verdicts
            ],
        }
        async with lock:
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{p.id}: 注入={gt_step.value} 预测={rec['pred_step']} {'HIT' if rec['hit'] else 'MISS'}")

    await asyncio.gather(*(one(*t) for t in tasks))

    recs = _load_jsonl(out)
    from hy3_oj.core.schemas import ProcessReview, ReviewStep
    pairs = [
        (ProcessReview(error_step=ReviewStep(r["pred_step"]) if r["pred_step"] else None), ReviewStep(r["injected_step"]))
        for r in recs
    ]
    print("\n===== 定位准确率 =====")
    print(json.dumps(localization_accuracy(pairs), ensure_ascii=False, indent=2))


def mode_fp(review_path: str) -> None:
    recs = _load_jsonl(review_path)
    from hy3_oj.core.schemas import ProcessReview, ProcessErrorType, ReviewStep
    reviews = [
        (r["problem_id"], ProcessReview(
            error_step=ReviewStep(r["error_step"]) if r["error_step"] else None,
            error_type=ProcessErrorType(r["error_type"]) if r["error_type"] else None,
            lucky_pass_flags=r["lucky_pass_flags"],
            process_score=r["process_score"],
        ))
        for r in recs if r.get("answer_passed")
    ]
    candidates = false_positive_candidates(reviews)
    spot_path = Path(review_path).with_suffix(".spot_check.json")
    if not spot_path.exists():
        spot_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已生成待人工抽检清单 {spot_path}（{len(candidates)} 条），请人工填 human_verdict 后重跑本命令")
        return
    checks = json.loads(spot_path.read_text(encoding="utf-8"))
    print("===== 误报率 =====")
    print(json.dumps(false_positive_rate(checks), ensure_ascii=False, indent=2))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["review", "inject", "fp"], required=True)
    ap.add_argument("--subset")
    ap.add_argument("--solutions")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    if args.mode == "fp":
        mode_fp(args.out)
        return

    cfg = load_config()
    problems = load_subset(args.subset)
    client = Hy3Client(cfg)

    if args.mode == "review":
        solutions = {r["problem_id"]: r for r in _load_jsonl(args.solutions)}
        await mode_review(client, problems, solutions, args.out, args.concurrency, cfg)
    elif args.mode == "inject":
        await mode_inject(client, problems, args.out, args.limit, args.concurrency)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
