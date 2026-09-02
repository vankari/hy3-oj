"""批量评测驱动（D11 正式集）。

两阶段，均逐题 append 落盘 jsonl（中断可 resume）：

1. ``run_subset``：并发跑闭环解题（并发受容器池/额度约束），单题异常不中断整批；
2. ``run_reviews``：对闭环解**全量**跑 Reviewer 过程评估（AC 解含行为探针蒙对检测）。

阶段解耦的原因：闭环耗 token/时长远大于审查，分开跑可分别续跑与重试。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable

from hy3_oj.agents import reviewer
from hy3_oj.core.schemas import Plan, Problem, Solution
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor


def load_jsonl(path: str | Path) -> list[dict]:
    """读取 jsonl（空文件/不存在返回 []）。"""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: str | Path, rec: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def load_plan_from_trace(trace_file: str) -> Plan | None:
    """从轨迹文件取最终 Plan（PLAN/PLANNED 事件；PLAN 为末态，优先）。"""
    p = Path(trace_file) if trace_file else None
    if not p or not p.exists():
        return None
    fallback: Plan | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("state") == "PLAN" and "plan" in e:
            return Plan(**e["plan"])
        if e.get("state") == "PLANNED" and "plan" in e and fallback is None:
            fallback = Plan(**e["plan"])
    return fallback


async def run_subset(
    problems: list[Problem],
    pipeline,
    out: str | Path,
    concurrency: int = 4,
    resume: bool = True,
    log: Callable[[str], None] = print,
    retries: int = 1,
) -> list[dict]:
    """在子集上并发跑闭环解题，返回全部记录（含本次之前已完成的）。

    retries：单题异常（沙箱/网络抖动）重试次数；长批次跑批时避免基础设施抖动被记成能力失败。
    """
    done = {r["problem_id"] for r in load_jsonl(out)} if resume and Path(out).exists() else set()
    todo = [p for p in problems if p.id not in done]
    log(f"[solve] 子集 {len(problems)} 题，已完成 {len(done)}，待跑 {len(todo)}，并发 {concurrency}")

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    t0 = time.time()
    counters = {"ok": 0, "fail": 0, "err": 0}
    done_n = 0

    async def one(i: int, p: Problem) -> None:
        nonlocal done_n
        async with sem:
            rec: dict | None = None
            errored = False
            for attempt in range(retries + 1):
                try:
                    rec = await pipeline.solve(p)
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt >= retries:
                        rec = {"problem_id": p.id, "difficulty": p.difficulty, "passed": False,
                               "rounds": None, "code": "", "error": f"{type(e).__name__}: {e}"}
                        errored = True
                        counters["err"] += 1
                    else:
                        log(f"[{i}] {p.id} 第 {attempt + 1} 次异常（{type(e).__name__}），重试")
            assert rec is not None
            if not errored:
                counters["ok" if rec.get("passed") else "fail"] += 1
        async with lock:
            _append(out, rec)
            done_n += 1
            elapsed = time.time() - t0
            eta = elapsed / max(done_n, 1) * (len(todo) - done_n)
            flag = "PASS" if rec.get("passed") else "FAIL"
            log(f"[{i}/{len(todo)}] {p.id} ({p.difficulty}) {flag} "
                f"rounds={rec.get('rounds', '-')} | 累计通过 {counters['ok']}/{done_n} | ETA {eta / 60:.0f}min")

    await asyncio.gather(*(one(i, p) for i, p in enumerate(todo, 1)))
    log(f"[solve] 完成：通过 {counters['ok']}，失败 {counters['fail']}，异常 {counters['err']}，"
        f"耗时 {(time.time() - t0) / 60:.1f}min")
    return load_jsonl(out)


async def run_reviews(
    problems: list[Problem],
    solve_records: list[dict],
    cfg: dict,
    out: str | Path,
    concurrency: int = 6,
    resume: bool = True,
    client: Hy3Client | None = None,
    executor: DockerExecutor | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """对闭环解全量跑 Reviewer（五段式审查 + AC 解蒙对探针），返回审查记录。"""
    by_id = {r["problem_id"]: r for r in solve_records}
    targets = [p for p in problems if p.id in by_id and by_id[p.id].get("code")]
    done = {r["problem_id"] for r in load_jsonl(out)} if resume and Path(out).exists() else set()
    todo = [p for p in targets if p.id not in done]
    log(f"[review] 可审查 {len(targets)} 题，已完成 {len(done)}，待跑 {len(todo)}，并发 {concurrency}")
    if not todo:
        return load_jsonl(out)

    own_client = client is None
    client = client or Hy3Client(cfg)
    own_executor = executor is None
    executor = executor or DockerExecutor(cfg)

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    done_n = 0
    t0 = time.time()

    async def one(i: int, p: Problem) -> None:
        nonlocal done_n
        rec = by_id[p.id]
        plan = load_plan_from_trace(rec.get("trace_file", ""))
        verdict_summary = ("AC（全部测试点通过）" if rec.get("passed")
                           else f"未通过（{rec.get('rounds', 0)} 轮修复后仍失败）")
        async with sem:
            rev = await reviewer.review(
                client, p, plan, Solution(code=rec["code"]), verdict_summary,
                executor=executor, answer_passed=bool(rec.get("passed")),
            )
        out_rec = {
            "problem_id": p.id,
            "difficulty": p.difficulty,
            "answer_passed": bool(rec.get("passed")),
            "process_score": rev.process_score,
            "error_step": rev.error_step.value if rev.error_step else None,
            "error_type": rev.error_type.value if rev.error_type else None,
            "lucky_pass_flags": rev.lucky_pass_flags,
            "step_verdicts": [{"step": sv.step.value, "passed": sv.passed,
                               "evidence": sv.evidence[:160]} for sv in rev.step_verdicts],
        }
        async with lock:
            _append(out, out_rec)
            done_n += 1
            tag = " [蒙对?]" if out_rec["lucky_pass_flags"] else ""
            log(f"[{i}/{len(todo)}] {p.id} answer={'AC' if rec.get('passed') else 'FAIL'} "
                f"process={rev.process_score:.2f}{tag}")

    try:
        await asyncio.gather(*(one(i, p) for i, p in enumerate(todo, 1)))
    finally:
        if own_executor:
            executor.close()
        if own_client:
            await client.close()
    log(f"[review] 完成 {done_n} 题，耗时 {(time.time() - t0) / 60:.1f}min")
    return load_jsonl(out)
