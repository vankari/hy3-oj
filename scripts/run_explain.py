"""入口：解题 + 过程评估 + 成文题解（一体化，面向外部题目）。

支持外部 md/txt 题目输入（--file / --dir），输出：代码 + 判题结论 + 过程评估 + 题解。

用法：
    python scripts/run_explain.py --file problems/my.md --out runs/explain/my.md
    python scripts/run_explain.py --dir problems/ --out runs/explain/
    python scripts/run_explain.py --subset data/subsets/subset_lcb_v1.jsonl --id "leetcode:3265" --out runs/explain/
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from hy3_oj.agents import explainer, reviewer
from hy3_oj.core.config import load_config
from hy3_oj.core.pipeline import SolvePipeline
from hy3_oj.core.problem_io import load_problem_file, load_problems_dir
from hy3_oj.core.schemas import Plan, Problem
from hy3_oj.data.subset import load_subset


def _load_plan(trace_file: str) -> Plan | None:
    import json

    p = Path(trace_file) if trace_file else None
    if not p or not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("state") in ("PLAN", "PLANNED") and "plan" in e:
            return Plan(**e["plan"])
    return None


async def handle(problem: Problem, pipeline: SolvePipeline, out_path: Path) -> None:
    print(f"[solve] {problem.id} ({problem.difficulty})")
    result = await pipeline.solve(problem)
    plan = _load_plan(result.get("trace_file", ""))

    verdict = "AC（全部测试点通过）" if result["passed"] else f"未通过（{result.get('rounds', 0)} 轮修复后仍失败）"
    review = await reviewer.review(
        pipeline.client, problem, plan,
        __import__("hy3_oj.core.schemas", fromlist=["Solution"]).Solution(code=result["code"]),
        verdict,
    )
    print(f"[review] process_score={review.process_score} "
          f"error_step={review.error_step.value if review.error_step else None} "
          f"lucky={review.lucky_pass_flags or '无'}")

    print("[explain] 生成题解...")
    md = await explainer.explain(
        pipeline.client, problem,
        __import__("hy3_oj.core.schemas", fromlist=["Solution"]).Solution(code=result["code"]),
        plan=plan, review=review, judge_summary=verdict,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# 题解：{problem.id}\n\n"
        f"> 难度：{problem.difficulty} ｜ 判题结论：{verdict}\n"
        f"> 过程评分：{review.process_score:.2f}"
        + (f" ｜ 蒙对标记：{review.lucky_pass_flags}" if review.lucky_pass_flags else "")
        + "\n\n---\n\n"
    )
    code_block = (
        f"\n\n---\n\n## 最终代码\n\n```python\n{result['code']}\n```\n"
    )
    out_path.write_text(header + md + code_block, encoding="utf-8")
    print(f"[done] -> {out_path}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--dir")
    ap.add_argument("--subset")
    ap.add_argument("--id")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--out", default="runs/explain")
    args = ap.parse_args()

    if args.file:
        problems = [load_problem_file(args.file)]
    elif args.dir:
        problems = load_problems_dir(args.dir)
    elif args.subset:
        problems = load_subset(args.subset)
        if args.id:
            problems = [p for p in problems if p.id == args.id]
        else:
            problems = problems[: args.limit]
    else:
        raise SystemExit("需指定 --file / --dir / --subset 之一")

    out_dir = Path(args.out)
    pipeline = SolvePipeline(load_config())
    try:
        for p in problems:
            await handle(p, pipeline, out_dir / f"{p.id.replace(':', '_')}.md")
    finally:
        await pipeline.client.close()
        pipeline.executor.close()


if __name__ == "__main__":
    asyncio.run(main())
