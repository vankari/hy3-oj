"""入口：单轮直出基线（D3）。

流程：子集 → Coder 单次直出（无闭环、无对拍）→ Docker 判题 → pass@1 落盘。
判题用 public+private+generated 全部测试点（与 CodeContests 官方口径一致）。
断点续跑：已落盘结果的 problem_id 自动跳过。

用法：
    python scripts/run_baseline.py --subset data/subsets/subset_smoke.jsonl --out runs/baseline_smoke.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hy3_oj.agents import coder
from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import GenMode, Problem, Verdict
from hy3_oj.data.subset import load_subset
from hy3_oj.llm.client import Hy3Client
from hy3_oj.llm.pricing import summarize
from hy3_oj.sandbox.docker_executor import DockerExecutor


async def solve_one(client: Hy3Client, executor: DockerExecutor, problem: Problem) -> dict:
    sols = await coder.generate(client, problem, k=1, mode=GenMode.FAST)
    tests = problem.public_tests + problem.private_tests + problem.generated_tests
    results = await asyncio.to_thread(executor.execute, sols[0], tests)
    verdicts = [r.verdict.value for r in results]
    passed = bool(results) and all(v == "AC" for v in verdicts)
    return {
        "problem_id": problem.id,
        "difficulty": problem.difficulty,
        "passed": passed,
        "n_tests": len(results),
        "verdicts": verdicts,
        "first_fail": next((v for v in verdicts if v != "AC"), None),
        "code": sols[0].code,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    cfg = load_config()
    problems = load_subset(args.subset)[: args.limit]
    done = _load_done(args.out)
    todo = [p for p in problems if p.id not in done]
    print(f"子集 {len(problems)} 题，已完成 {len(done)}，待跑 {len(todo)}")

    client = Hy3Client(cfg)
    executor = DockerExecutor(cfg)
    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(p: Problem) -> dict:
        async with sem:
            try:
                return await solve_one(client, executor, p)
            except Exception as e:  # noqa: BLE001
                return {"problem_id": p.id, "difficulty": p.difficulty, "passed": False,
                        "error": f"{type(e).__name__}: {e}"}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = asyncio.Lock()

    async def run_and_record(i: int, p: Problem) -> None:
        rec = await guarded(p)
        async with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(todo)}] {p.id} ({p.difficulty}): {'PASS' if rec['passed'] else 'FAIL'} {rec.get('first_fail') or rec.get('error', '')}")

    await asyncio.gather(*(run_and_record(i, p) for i, p in enumerate(todo, 1)))

    await client.close()
    executor.close()

    records = _load_records(args.out)
    _report(records)
    print("token 用量:", json.dumps(summarize().get("by_mode", {}), ensure_ascii=False))


def _load_done(path: str) -> set[str]:
    return {r["problem_id"] for r in _load_records(path)}


def _load_records(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _report(records: list[dict]) -> None:
    n = len(records)
    if not n:
        return
    passed = sum(1 for r in records if r["passed"])
    print(f"\n===== 基线 pass@1: {passed}/{n} = {passed / n:.1%} =====")
    by_diff: dict[str, list[dict]] = {}
    for r in records:
        by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
    for d, rs in sorted(by_diff.items()):
        dp = sum(1 for r in rs if r["passed"])
        print(f"  {d}: {dp}/{len(rs)} = {dp / len(rs):.1%}")


if __name__ == "__main__":
    asyncio.run(main())
