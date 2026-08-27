"""入口：闭环解题评测（D7–D10）。在子集上跑完整闭环，与基线对比。

用法：
    python scripts/run_solve.py --subset data/subsets/subset_smoke.jsonl --out runs/closed_loop_smoke.jsonl [--limit 5] [--concurrency 2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hy3_oj.core.config import load_config
from hy3_oj.core.pipeline import SolvePipeline
from hy3_oj.data.subset import load_subset
from hy3_oj.llm.pricing import summarize


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=2, help="闭环单题 token 消耗大，默认低并发")
    args = ap.parse_args()

    cfg = load_config()
    problems = load_subset(args.subset)[: args.limit]
    done = _load_done(args.out)
    todo = [p for p in problems if p.id not in done]
    print(f"子集 {len(problems)}，已完成 {len(done)}，待跑 {len(todo)}")

    pipeline = SolvePipeline(cfg)
    sem = asyncio.Semaphore(args.concurrency)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = asyncio.Lock()

    async def run_one(i: int, p) -> None:
        async with sem:
            try:
                rec = await pipeline.solve(p)
            except Exception as e:  # noqa: BLE001
                rec = {"problem_id": p.id, "difficulty": p.difficulty, "passed": False,
                       "error": f"{type(e).__name__}: {e}"}
            async with lock:
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"[{i}/{len(todo)}] {p.id} ({p.difficulty}): {'PASS' if rec['passed'] else 'FAIL'} rounds={rec.get('rounds', '-')}")

    await asyncio.gather(*(run_one(i, p) for i, p in enumerate(todo, 1)))
    await pipeline.client.close()
    pipeline.executor.close()

    recs = _load_records(args.out)
    n = len(recs)
    passed = sum(1 for r in recs if r["passed"])
    if n:
        print(f"\n===== 闭环 pass@1: {passed}/{n} = {passed / n:.1%}（基线 41.9%）=====")
        by_diff: dict[str, list] = {}
        for r in recs:
            by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
        for d, rs in sorted(by_diff.items()):
            dp = sum(1 for r in rs if r["passed"])
            print(f"  {d}: {dp}/{len(rs)} = {dp / len(rs):.1%}")
        rounds = [r["rounds"] for r in recs if r.get("passed") and "rounds" in r]
        if rounds:
            print(f"  平均收敛轮数（通过题）: {sum(rounds) / len(rounds):.1f}")
    print("token 用量:", json.dumps(summarize().get("by_mode", {}), ensure_ascii=False))


def _load_done(path: str) -> set[str]:
    return {r["problem_id"] for r in _load_records(path)}


def _load_records(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    asyncio.run(main())
