"""解题闭环状态机（D7 核心）。

流程（详见 docs/项目架构设计.md §3.2）：
  Parser → Planner(慢) → Coder(快,K路) → 样例预筛 → 全量判题
    AC → DONE；失败 → Reflector(慢) 归因修复 → 回到全量判题（≤N 轮）
每步事件落盘 runs/trace/<problem_id>.jsonl，支持轨迹回放（Reviewer/Demo 的输入）。
"""
from __future__ import annotations

import asyncio
import json
import re
from enum import Enum
from pathlib import Path

from hy3_oj.agents import coder, parser, planner, reflector
from hy3_oj.core.schemas import GenMode, JudgeResult, Plan, Problem, Solution, Verdict
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor


class State(str, Enum):
    PARSED = "PARSED"
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    LOCAL_TESTED = "LOCAL_TESTED"
    JUDGED = "JUDGED"
    REFLECTED = "REFLECTED"
    DONE = "DONE"
    FAILED = "FAILED"


class SolvePipeline:
    """单题闭环解题编排器。"""

    def __init__(self, config: dict, client: Hy3Client | None = None, executor: DockerExecutor | None = None) -> None:
        self.config = config
        self.max_rounds: int = config["solve"]["max_repair_rounds"]
        self.k_samples: int = config["solve"]["k_samples"]
        self.temperatures: list[float] = config["solve"]["temperatures"]
        self.client = client or Hy3Client(config)
        self.executor = executor or DockerExecutor(config)
        self.trace_dir = Path(config["eval"]["runs_dir"]) / "trace"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    async def solve(self, problem: Problem) -> dict:
        """闭环解题主流程。返回结果 dict（passed/rounds/code/trace_file）。"""
        trace: list[dict] = []

        # 1. Parser（快思考结构化；失败则用原题面）
        try:
            problem = await parser.parse(self.client, problem)
        except Exception as e:  # noqa: BLE001
            trace.append({"state": State.PARSED, "warn": f"parser fallback: {e}"})

        # 2. Planner（慢思考；失败则空 plan 直出）
        try:
            plan: Plan | None = await planner.plan(self.client, problem)
            trace.append({"state": State.PLANNED, "plan": plan.model_dump()})
        except Exception as e:  # noqa: BLE001
            plan = None
            trace.append({"state": State.PLANNED, "warn": f"planner fallback: {e}"})

        # 3. Coder K 路采样（快思考）
        solutions = await coder.generate(
            self.client, problem, plan, k=self.k_samples,
            temperatures=self.temperatures, mode=GenMode.FAST,
        )
        trace.append({"state": State.GENERATED, "k": len(solutions)})

        # 4. 样例预筛：先在题面样例上跑，保留至少一个全过的解；全灭则取第一个
        sample_tests = problem.samples or problem.public_tests[:2]
        candidate = solutions[0]
        if sample_tests:
            for sol in solutions:
                results = await asyncio.to_thread(self.executor.execute, sol, sample_tests)
                if results and all(r.verdict == Verdict.AC for r in results):
                    candidate = sol
                    break
        trace.append({"state": State.LOCAL_TESTED, "chosen_temperature": candidate.temperature})

        # 5. 全量判题 + 反思修复闭环
        all_tests = problem.public_tests + problem.private_tests + problem.generated_tests
        current = candidate
        for round_idx in range(self.max_rounds + 1):
            results = await asyncio.to_thread(self.executor.execute, current, all_tests)
            verdicts = [r.verdict for r in results]
            passed = bool(results) and all(v == Verdict.AC for v in verdicts)
            trace.append({
                "state": State.JUDGED, "round": round_idx, "passed": passed,
                "verdicts": [v.value for v in verdicts],
            })
            if passed:
                self._dump_trace(problem.id, trace)
                return {"problem_id": problem.id, "difficulty": problem.difficulty,
                        "passed": True, "rounds": round_idx, "code": current.code,
                        "trace_file": str(self.trace_dir / f"{self._safe_name(problem.id)}.jsonl")}

            if round_idx >= self.max_rounds:
                break

            first_fail = next(r for r in results if r.verdict != Verdict.AC)
            try:
                reflection, fixed_code = await reflector.reflect(
                    self.client, problem, plan, current, first_fail, round_idx,
                )
                if fixed_code and fixed_code != current.code:
                    current = Solution(code=fixed_code, temperature=current.temperature, gen_mode=GenMode.SLOW)
                trace.append({"state": State.REFLECTED, "round": round_idx,
                              "cause": reflection.cause_class.value, "diagnosis": reflection.diagnosis[:200]})
            except Exception as e:  # noqa: BLE001
                trace.append({"state": State.REFLECTED, "round": round_idx, "warn": f"reflect failed: {e}"})
                break

        self._dump_trace(problem.id, trace)
        return {"problem_id": problem.id, "difficulty": problem.difficulty,
                "passed": False, "rounds": self.max_rounds, "code": current.code,
                "trace_file": str(self.trace_dir / f"{self._safe_name(problem.id)}.jsonl")}

    @staticmethod
    def _safe_name(problem_id: str) -> str:
        """题 id 可能含空格/斜杠等非法文件名字符（如 'p00035 Is it Convex?'）。"""
        return re.sub(r"[^\w\-.]+", "_", problem_id)

    def _dump_trace(self, problem_id: str, trace: list[dict]) -> None:
        path = self.trace_dir / f"{self._safe_name(problem_id)}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for event in trace:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
