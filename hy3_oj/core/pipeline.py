"""解题闭环状态机（D7 核心，v3 增强版）。

流程（详见 docs/项目架构设计.md §3.2）：
  多解特判(多解题) → Parser → 深分析(hard,慢思考) → Planner → Coder(K路,难度自适应)
  → Tester(小样例+暴力对拍oracle) 预筛 → top-k 候选 → 全量判题
    AC → DONE；失败 → Reflector 并行修复 / Refine 重规划（轮数难度自适应）
每步事件落盘 runs/trace/<problem_id>.jsonl，支持轨迹回放（Reviewer/Demo 的输入）。

v3（2026-09-01，提升空间 #1/#2/#4 + 618_B 根因修复）：
- 多解题 LLM 特判 checker（sandbox/special_judge.py）：精确比对误杀合法解的根修；
- hard 档：k/修复轮数加大 + 慢思考自由文本深分析注入规划上下文；
- 预筛差分对拍：AI 小样例上以样例验证过的暴力解为 oracle，拦截"过样例错边界"；
- top-2 候选并行修复：预筛前两名同时进入修复环，任一 AC 即收。
"""
from __future__ import annotations

import asyncio
import json
import re
from enum import Enum
from pathlib import Path

from hy3_oj.agents import coder, parser, planner, reflector, tester
from hy3_oj.agents.coder import is_call_based as is_call_based_problem
from hy3_oj.core.schemas import GenMode, JudgeResult, Language, Plan, Problem, Solution, Verdict
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox import special_judge
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
        solve_cfg = config["solve"]
        self.max_rounds: int = solve_cfg["max_repair_rounds"]
        self.k_samples: int = solve_cfg["k_samples"]
        self.temperatures: list[float] = solve_cfg["temperatures"]
        self.client = client or Hy3Client(config)
        self.executor = executor or DockerExecutor(config)
        self.trace_dir = Path(config["eval"]["runs_dir"]) / "trace"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    async def solve(self, problem: Problem) -> dict:
        """闭环解题主流程。返回结果 dict（passed/rounds/code/trace_file）。"""
        trace: list[dict] = []
        solve_cfg = self.config["solve"]
        is_hard = problem.difficulty == "hard"
        is_medium = problem.difficulty == "medium"
        # 难度自适应 k：easy=6 / medium=8 / hard=12（90+ 攻坚）
        if is_hard:
            k = solve_cfg.get("k_samples_hard", self.k_samples)
        elif is_medium:
            k = solve_cfg.get("k_samples_medium", self.k_samples)
        else:
            k = self.k_samples
        max_rounds = solve_cfg.get("max_repair_rounds_hard", self.max_rounds) if is_hard else self.max_rounds
        top_k = max(1, int(solve_cfg.get("repair_top_k", 2)))

        # 0. 多解特判：题面提示答案不唯一 → LLM checker（参考解反向验证，不可信则回退精确比对）
        checker_code: str | None = None
        if (
            solve_cfg.get("special_judge", True)
            and special_judge.needs_special_judge(problem)
            and problem.reference_solutions
        ):
            try:
                checker_code = await special_judge.get_checker(self.client, self.executor, problem)
                trace.append({"state": "SPECIAL_JUDGE", "ok": checker_code is not None})
            except Exception as e:  # noqa: BLE001
                trace.append({"state": "SPECIAL_JUDGE", "warn": f"special judge fallback: {e}"})

        # 1. Parser（快思考结构化；失败则用原题面）
        try:
            problem = await parser.parse(self.client, problem)
        except Exception as e:  # noqa: BLE001
            trace.append({"state": State.PARSED, "warn": f"parser fallback: {e}"})

        # 2. hard 档慢思考深分析（自由文本，注入后续规划上下文）
        if problem.difficulty in solve_cfg.get("deep_analysis_difficulties", ["hard"]):
            try:
                analysis = await planner.deep_analyze(self.client, problem)
                problem = problem.model_copy(update={
                    "constraints": f"{problem.constraints}\n\n深度分析：\n{analysis[:3000]}".strip()
                })
                trace.append({"state": "DEEP_ANALYSIS", "chars": len(analysis)})
            except Exception as e:  # noqa: BLE001
                trace.append({"state": "DEEP_ANALYSIS", "warn": f"deep analysis fallback: {e}"})

        # 3. Planner（快思考结构化；失败则空 plan 直出）
        try:
            plan: Plan | None = await planner.plan(self.client, problem)
            trace.append({"state": State.PLANNED, "plan": plan.model_dump()})
        except Exception as e:  # noqa: BLE001
            plan = None
            trace.append({"state": State.PLANNED, "warn": f"planner fallback: {e}"})

        # 4. Coder K 路采样（快思考，k 难度自适应）
        # 90+ 攻坚：medium/hard 档多 Plan 多样性——多算法范式分别采样，覆盖多种正确解
        n_plans = int(solve_cfg.get("n_diverse_plans", 3)) if problem.difficulty in ("medium", "hard") else 1
        if n_plans > 1:
            try:
                plans = await planner.plan_diverse(self.client, problem, n=n_plans)
                trace.append({"state": "PLAN_DIVERSE", "n": len(plans),
                              "tags": [p.algorithm_tags for p in plans]})
            except Exception as e:  # noqa: BLE001
                plans = [plan] if plan else []
                trace.append({"state": "PLAN_DIVERSE", "warn": f"diverse fallback: {e}"})
        else:
            plans = [plan] if plan else [None]

        # 采样预算分配：主 plan 拿 60%（保证单思路深度），备选 plan 分剩余 40%（保证多样性）
        # 教训：均分会让每个 plan 只采 2~4 个样本，单思路深度不足反而掉分（v5 实测回归）
        main_ratio = float(solve_cfg.get("main_plan_ratio", 0.6))
        n_plans_total = max(1, len(plans))
        k_main = max(2, int(k * main_ratio))
        k_alt_each = max(1, (k - k_main) // max(1, n_plans_total - 1)) if n_plans_total > 1 else 0

        solutions: list[Solution] = []
        for p_i, one_plan in enumerate(plans):
            k_i = k_main if p_i == 0 else k_alt_each
            sols = await coder.generate(
                self.client, problem, one_plan, k=k_i,
                temperatures=self.temperatures, mode=GenMode.FAST,
            )
            for s in sols:
                s.plan_ref = f"plan{p_i}"
            solutions.extend(sols)
        trace.append({"state": State.GENERATED, "k": len(solutions), "difficulty": problem.difficulty,
                      "n_plans": n_plans_total, "k_main": k_main, "k_alt_each": k_alt_each})

        # 5. Tester：小样例 + 暴力对拍 oracle（暴力解先过样例才可信）
        sample_tests = problem.samples or problem.public_tests[:2]
        ai_tests = []
        brute = None
        try:
            ai_tests = await tester.gen_tests(self.client, problem, n=4)
            if solve_cfg.get("brute_force_oracle", True):
                brute = await tester.gen_brute_force(self.client, problem, self.executor)
            trace.append({"state": "TEST_GEN", "n": len(ai_tests), "brute": brute is not None})
        except Exception as e:  # noqa: BLE001
            trace.append({"state": "TEST_GEN", "warn": f"tester fallback: {e}"})

        # 6. 预筛：样例精确比对（含特判）+ AI 小样例验证 → 综合得分取 top-k
        scored: list[tuple[int, int, Solution]] = []
        for sol in solutions:
            n_sample = 0
            if sample_tests:
                results = await asyncio.to_thread(self.executor.execute, sol, sample_tests, checker_code)
                n_sample = sum(1 for r in results if r.verdict == Verdict.AC)
            n_diff = 0
            if checker_code and ai_tests:
                # 多解题：差分对拍会误罚"合法但不同"的输出，AI 用例改用 checker 验证
                results_ai = await asyncio.to_thread(self.executor.execute, sol, ai_tests, checker_code)
                n_diff = sum(1 for r in results_ai if r.verdict == Verdict.AC)
            elif brute and ai_tests:
                mismatches = await asyncio.to_thread(
                    tester.differential_mismatches, self.executor, sol.code, brute,
                    [t.input for t in ai_tests],
                )
                n_diff = len(ai_tests) - len(mismatches)
            scored.append((n_sample, n_diff, sol))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        pool = [s for _, _, s in scored[:top_k]]
        trace.append({"state": State.LOCAL_TESTED,
                      "scores": [[a, b] for a, b, _ in scored],
                      "pool": len(pool), "top_k": top_k})

        # 7. 全量判题 + top-k 并行修复闭环
        all_tests = problem.public_tests + problem.private_tests + problem.generated_tests
        used_cpp = False  # C++17 兜底只允许触发一次，避免无限循环
        # while 而非 for：C++ 兜底会重置 round_idx，for 循环的迭代器会覆盖该赋值
        # 导致 C++ 代码生成后从未被判题（v9 实测：CPP_FALLBACK 后无任何 JUDGED）
        round_idx = 0
        while round_idx <= max_rounds:
            judged: list[list[JudgeResult]] = await asyncio.gather(*[
                asyncio.to_thread(self.executor.execute, c, all_tests, checker_code) for c in pool
            ])
            winner: Solution | None = None
            for ci, (cand, results) in enumerate(zip(pool, judged)):
                verdicts = [r.verdict for r in results]
                passed = bool(results) and all(v == Verdict.AC for v in verdicts)
                trace.append({"state": State.JUDGED, "round": round_idx, "cand": ci,
                              "passed": passed, "verdicts": [v.value for v in verdicts]})
                if passed and winner is None:
                    winner = cand
            if winner is not None:
                self._dump_trace(problem.id, trace, plan, winner)
                return {"problem_id": problem.id, "difficulty": problem.difficulty,
                        "passed": True, "rounds": round_idx, "code": winner.code,
                        "trace_file": str(self.trace_dir / f"{self._safe_name(problem.id)}.jsonl")}

            # C++17 兜底：Python 路径已到最后一轮仍失败时，改用 C++17 再战一轮
            # （hard 档 TLE 攻坚：Python 性能不足；call-based 题不适用——驱动为 Python）
            cpp_enabled = bool(solve_cfg.get("cpp_fallback", False))
            cpp_only_diff = solve_cfg.get("cpp_fallback_difficulties", ["hard"])
            if (
                round_idx >= max_rounds
                and cpp_enabled
                and not used_cpp
                and problem.difficulty in cpp_only_diff
                and not is_call_based_problem(problem)
            ):
                try:
                    used_cpp = True
                    cpp_sols = await coder.generate(
                        self.client, problem, plan, k=2,
                        temperatures=[0.2, 0.6], mode=GenMode.FAST, language=Language.CPP17,
                    )
                    pool = cpp_sols
                    trace.append({"state": "CPP_FALLBACK", "k": len(cpp_sols)})
                    round_idx = 0  # 重置轮数，给 C++ 一轮完整的判题+修复机会
                    continue
                except Exception as e:  # noqa: BLE001
                    trace.append({"state": "CPP_FALLBACK", "warn": f"cpp fallback failed: {e}"})

            # refine：连续失败（round_idx>=1）→ 重规划换范式再生成，整池替换
            if round_idx >= 1 and plan is not None:
                first_fail = next(r for r in judged[0] if r.verdict != Verdict.AC)
                try:
                    ft = first_fail.failed_test
                    counter_example = (
                        f"\n失败反例输入：\n{ft.input[:400]}\n期望：{(ft.expected_output or '')[:200]}\n"
                        f"实际差异：{first_fail.diff_excerpt[:300]}\n" if ft else ""
                    )
                    replan_prompt_note = (
                        f"此前按 {plan.algorithm_tags} 实现连续 {round_idx + 1} 轮未通过"
                        f"（最近失败：{first_fail.verdict.value}）。{counter_example}"
                        "请重新规划，必要时更换算法范式。"
                    )
                    new_plan_problem = problem.model_copy(update={
                        "constraints": f"{problem.constraints}\n\n{replan_prompt_note}".strip()
                    })
                    plan = await planner.plan(self.client, new_plan_problem)
                    pool = await coder.generate(self.client, problem, plan, k=2,
                                                temperatures=[0.4, 0.7], mode=GenMode.FAST)
                    trace.append({"state": "REFINED", "round": round_idx,
                                  "new_tags": plan.algorithm_tags})
                    round_idx += 1  # while 循环需显式递增（原 for 由迭代器处理）
                    continue
                except Exception as e:  # noqa: BLE001
                    trace.append({"state": "REFINED", "round": round_idx, "warn": f"refine failed: {e}"})

            # 并行修复池中全部候选
            async def fix_one(cand: Solution, results: list[JudgeResult]) -> Solution:
                first_fail = next(r for r in results if r.verdict != Verdict.AC)
                _reflection, fixed_code = await reflector.reflect(
                    self.client, problem, plan, cand, first_fail, round_idx,
                )
                if fixed_code and fixed_code != cand.code:
                    return Solution(code=fixed_code, language=cand.language,
                                    temperature=cand.temperature, gen_mode=GenMode.SLOW)
                return cand

            try:
                pool = list(await asyncio.gather(*[fix_one(c, r) for c, r in zip(pool, judged)]))
                trace.append({"state": State.REFLECTED, "round": round_idx, "pool": len(pool)})
            except Exception as e:  # noqa: BLE001
                trace.append({"state": State.REFLECTED, "round": round_idx, "warn": f"reflect failed: {e}"})
                break
            round_idx += 1

        final = pool[0]
        self._dump_trace(problem.id, trace, plan, final)
        return {"problem_id": problem.id, "difficulty": problem.difficulty,
                "passed": False, "rounds": max_rounds, "code": final.code,
                "trace_file": str(self.trace_dir / f"{self._safe_name(problem.id)}.jsonl")}

    @staticmethod
    def _safe_name(problem_id: str) -> str:
        """题 id 可能含空格/斜杠等非法文件名字符（如 'p00035 Is it Convex?'）。"""
        return re.sub(r"[^\w\-.]+", "_", problem_id)

    def _dump_trace(self, problem_id: str, trace: list[dict], plan: Plan | None = None, final: Solution | None = None) -> None:
        """轨迹落盘：事件序列 + Plan 与最终解（Reviewer 过程审查的完整输入）。"""
        path = self.trace_dir / f"{self._safe_name(problem_id)}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for event in trace:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            if plan is not None:
                f.write(json.dumps({"state": "PLAN", "plan": plan.model_dump()}, ensure_ascii=False, default=str) + "\n")
            if final is not None:
                f.write(json.dumps({"state": "FINAL", "code": final.code}, ensure_ascii=False, default=str) + "\n")
