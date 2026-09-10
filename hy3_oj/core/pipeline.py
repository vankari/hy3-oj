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

    async def solve(self, problem: Problem, language: Language | None = None) -> dict:
        """闭环解题主流程。返回结果 dict（passed/rounds/code/trace_file/language_used/language_advice）。

        language: 显式指定 Language.PYTHON3 / Language.CPP17 则全程锁定该语言且不自动兜底；
        为 None 则自动模式（优先 Python3，失败后再诊断是否建议 C++17）。
        """
        trace: list[dict] = []
        trace_path = self.trace_dir / f"{self._safe_name(problem.id)}.jsonl"
        trace_path.write_text("", encoding="utf-8")  # 清空，逐步追加供 UI 实时轮询
        def emit(ev: dict) -> None:
            """追加事件到内存列表并即时落盘一行（UI 可轮询增量展示）。"""
            trace.append(ev)
            with open(trace_path, "a", encoding="utf-8") as _f:
                _f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        executor = self.executor.with_limits(problem.judge) if problem.judge else self.executor
        if problem.judge:
            emit({"state": "JUDGE_CONFIG", "judge": problem.judge.model_dump(),
                  "tests": len(problem.public_tests + problem.private_tests + problem.generated_tests)})
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
        from hy3_oj.sandbox.checkers import checker_source
        checker_code = checker_source(problem.judge.checker) if problem.judge and problem.judge.checker else None
        if (
            checker_code is None
            and solve_cfg.get("special_judge", True)
            and special_judge.needs_special_judge(problem)
            and problem.reference_solutions
        ):
            try:
                checker_code = await special_judge.get_checker(self.client, executor, problem)
                emit({"state": "SPECIAL_JUDGE", "ok": checker_code is not None})
            except Exception as e:  # noqa: BLE001
                emit({"state": "SPECIAL_JUDGE", "warn": f"special judge fallback: {e}"})

        # 1. Parser（快思考结构化；失败则用原题面）
        try:
            problem = await parser.parse(self.client, problem)
        except Exception as e:  # noqa: BLE001
            emit({"state": State.PARSED, "warn": f"parser fallback: {e}"})

        # 2. hard 档慢思考深分析（自由文本，注入后续规划上下文）
        if problem.difficulty in solve_cfg.get("deep_analysis_difficulties", ["hard"]):
            try:
                analysis = await planner.deep_analyze(self.client, problem)
                problem = problem.model_copy(update={
                    "constraints": f"{problem.constraints}\n\n深度分析：\n{analysis[:3000]}".strip()
                })
                emit({"state": "DEEP_ANALYSIS", "chars": len(analysis)})
            except Exception as e:  # noqa: BLE001
                emit({"state": "DEEP_ANALYSIS", "warn": f"deep analysis fallback: {e}"})

        # 3. Planner（快思考结构化；失败则空 plan 直出）
        try:
            plan: Plan | None = await planner.plan(self.client, problem)
            emit({"state": State.PLANNED, "plan": plan.model_dump()})
        except Exception as e:  # noqa: BLE001
            plan = None
            emit({"state": State.PLANNED, "warn": f"planner fallback: {e}"})

        # 4. Coder K 路采样（快思考，k 难度自适应）
        # 90+ 攻坚：medium/hard 档多 Plan 多样性——多算法范式分别采样，覆盖多种正确解
        n_plans = int(solve_cfg.get("n_diverse_plans", 3)) if problem.difficulty in ("medium", "hard") else 1
        if n_plans > 1:
            try:
                plans = await planner.plan_diverse(self.client, problem, n=n_plans)
                emit({"state": "PLAN_DIVERSE", "n": len(plans),
                              "tags": [p.algorithm_tags for p in plans]})
            except Exception as e:  # noqa: BLE001
                plans = [plan] if plan else []
                emit({"state": "PLAN_DIVERSE", "warn": f"diverse fallback: {e}"})
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
                language=language or Language.PYTHON3,
            )
            for s in sols:
                s.plan_ref = f"plan{p_i}"
            solutions.extend(sols)
        emit({"state": State.GENERATED, "k": len(solutions), "difficulty": problem.difficulty,
                      "n_plans": n_plans_total, "k_main": k_main, "k_alt_each": k_alt_each})

        # 5. Tester：边界用例 + 暴力对拍 oracle
        #  · 边界用例（gen_tests）：极小/极值/特殊结构，判题走差分对拍，不预填标答
        #  · 普通用例（gen_bf_tests）：一律用暴力解(bf)跑出 expected_output，标答正确有保障
        sample_tests = problem.samples or problem.public_tests[:2]
        ai_tests: list = []
        brute = None
        if not (problem.judge and problem.judge.tests_complete):
            try:
                if solve_cfg.get("brute_force_oracle", True):
                    brute = await tester.gen_brute_force(self.client, problem, executor)
                boundary_tests = await tester.gen_tests(self.client, problem, n=4)
                bf_tests = []
                if brute:
                    bf_tests = await tester.gen_bf_tests(
                        self.client, problem, executor, brute, n=8)
                ai_tests = boundary_tests + bf_tests
                emit({"state": "TEST_GEN", "n_boundary": len(boundary_tests),
                              "n_bf": len(bf_tests), "brute": brute is not None})
            except Exception as e:  # noqa: BLE001
                emit({"state": "TEST_GEN", "warn": f"tester fallback: {e}"})
        else:
            emit({"state": "TEST_GEN", "source": "provided", "skipped": True, "n_boundary": 0, "n_bf": 0, "brute": False})

        # 6. 预筛：样例精确比对（含特判）+ AI 小样例验证 → 综合得分取 top-k
        scored: list[tuple[int, int, Solution]] = []
        for sol in solutions:
            n_sample = 0
            if sample_tests:
                results = await asyncio.to_thread(executor.execute, sol, sample_tests, checker_code)
                n_sample = sum(1 for r in results if r.verdict == Verdict.AC)
            n_diff = 0
            if checker_code and ai_tests:
                # 多解题：差分对拍会误罚"合法但不同"的输出，AI 用例改用 checker 验证
                results_ai = await asyncio.to_thread(executor.execute, sol, ai_tests, checker_code)
                n_diff = sum(1 for r in results_ai if r.verdict == Verdict.AC)
            elif brute and ai_tests:
                mismatches = await asyncio.to_thread(
                    tester.differential_mismatches, executor, sol.code, brute,
                    [t.input for t in ai_tests],
                )
                n_diff = len(ai_tests) - len(mismatches)
            scored.append((n_sample, n_diff, sol))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        pool = [s for _, _, s in scored[:top_k]]
        emit({"state": State.LOCAL_TESTED,
                      "scores": [[a, b] for a, b, _ in scored],
                      "pool": len(pool), "top_k": top_k})

        # 7. 全量判题 + top-k 并行修复闭环
        # 官方测试集存在 → 仅用官方集（保持评测语义）；
        # 外部粘贴题（无 public/private）→ 用 AI 用例判题，分两类：
        #  · bf_tests（非边界）：标答由暴力解(bf oracle)生成，走标准输出对比，正确性保障
        #  · boundary_tests（边界）：走"候选 vs 暴力解"差分对拍，不预填标答
        std_tests = problem.public_tests + problem.private_tests + problem.generated_tests
        if std_tests:
            all_tests = std_tests
            boundary_for_judge: list = []
            bf_for_judge: list = []
        else:
            boundary_for_judge = [t for t in (ai_tests or []) if t.is_boundary]
            bf_for_judge = [t for t in (ai_tests or []) if not t.is_boundary]
            all_tests = boundary_for_judge + bf_for_judge
        used_cpp = False  # C++17 兜底只允许触发一次，避免无限循环

        async def _judge(cand: Solution) -> list[JudgeResult]:
            """判题：官方集/bf 标答用例走标准对比；边界用例走候选 vs 暴力解差分。"""
            emit({"state": "JUDGE_STARTED", "round": round_idx,
                  "language": cand.language.value, "code": cand.code})
            res_std = await asyncio.to_thread(
                executor.execute, cand, std_tests, checker_code)
            res_bf = await asyncio.to_thread(
                executor.execute, cand, bf_for_judge, checker_code)
            res_boundary: list[JudgeResult] = []
            if boundary_for_judge and brute:
                mism = await asyncio.to_thread(
                    tester.differential_mismatches, executor, cand.code, brute,
                    [t.input for t in boundary_for_judge],
                )
                bad = {m["input"] for m in mism}
                for t in boundary_for_judge:
                    is_bad = t.input[:120] in bad
                    res_boundary.append(JudgeResult(
                        verdict=Verdict.WA if is_bad else Verdict.AC,
                        failed_test=t if is_bad else None,
                        diff_excerpt=("候选解与暴力解(bf)在边界用例上输出不一致" if is_bad else ""),
                    ))
            # 顺序对齐 all_tests = (std_tests) | (boundary_for_judge + bf_for_judge)
            return res_std + res_boundary + res_bf
        # while 而非 for：C++ 兜底会重置 round_idx，for 循环的迭代器会覆盖该赋值
        # 导致 C++ 代码生成后从未被判题（v9 实测：CPP_FALLBACK 后无任何 JUDGED）
        round_idx = 0
        while round_idx <= max_rounds:
            judged: list[list[JudgeResult]] = await asyncio.gather(*[_judge(c) for c in pool])
            winner: Solution | None = None
            for ci, (cand, results) in enumerate(zip(pool, judged)):
                verdicts = [r.verdict for r in results]
                passed = bool(results) and all(v == Verdict.AC for v in verdicts)
                emit({"state": State.JUDGED, "round": round_idx, "cand": ci,
                              "passed": passed, "verdicts": [v.value for v in verdicts],
                              "language": cand.language.value, "code": cand.code,
                              "tests": [{"index": i, "verdict": r.verdict.value, "time_ms": r.time_ms,
                                         "stderr": r.stderr[:400], "diff": r.diff_excerpt[:400],
                                         "failed_input": r.failed_test.input[:500] if r.failed_test else None}
                                        for i, r in enumerate(results)]})
                if passed and winner is None:
                    winner = cand
            if winner is not None:
                emit({"state": "FINAL", "code": winner.code, "passed": True, "rounds": round_idx,
                      "language_used": winner.language.value})
                return {"problem_id": problem.id, "difficulty": problem.difficulty,
                        "passed": True, "rounds": round_idx, "code": winner.code,
                        "language_used": winner.language.value,
                        "judge": problem.judge.model_dump() if problem.judge else None,
                        "verification": ({"source": problem.source.value, "public": len(problem.public_tests),
                            "private": len(problem.private_tests), "generated": len(problem.generated_tests),
                            "total": len(all_tests), "passed": len(all_tests)}
                            if problem.judge and problem.judge.tests_complete else None),
                        "plan": plan.model_dump() if plan else None,
                        "trace_file": str(self.trace_dir / f"{self._safe_name(problem.id)}.jsonl")}

            # C++17 兜底：Python 路径已到最后一轮仍失败时，改用 C++17 再战一轮
            # （hard 档 TLE 攻坚：Python 性能不足；call-based 题不适用——驱动为 Python）
            cpp_enabled = bool(solve_cfg.get("cpp_fallback", False))
            cpp_only_diff = solve_cfg.get("cpp_fallback_difficulties", ["hard"])
            if (
                round_idx >= max_rounds
                and cpp_enabled
                and not used_cpp
                and language is None  # 显式指定语言时不自动兜底
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
                    emit({"state": "CPP_FALLBACK", "k": len(cpp_sols)})
                    round_idx = 0  # 重置轮数，给 C++ 一轮完整的判题+修复机会
                    continue
                except Exception as e:  # noqa: BLE001
                    emit({"state": "CPP_FALLBACK", "warn": f"cpp fallback failed: {e}"})

            # 记录本轮历史最优解（按通过测试点数）：refine 不得丢弃进展
            # （教训：整池替换会把"已通过 96/102"的接近解丢掉换新解，
            #   导致 easy/medium 的接近题反复回到起点——513_A/709_D 实测）
            best_cand: Solution | None = None
            best_pass = -1
            for cand, results in zip(pool, judged):
                n_pass = sum(1 for r in results if r.verdict == Verdict.AC)
                if n_pass > best_pass:
                    best_cand, best_pass = cand, n_pass

            # refine：连续失败（round_idx>=1）→ 重规划换范式再生成
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
                    new_pool = await coder.generate(self.client, problem, plan, k=2,
                                                    temperatures=[0.4, 0.7], mode=GenMode.FAST,
                                                    language=language or (best_cand.language if best_cand else Language.PYTHON3))
                    # 保留历史最优解一并进入下一轮，避免进展被丢弃
                    pool = new_pool + ([best_cand] if best_cand is not None else [])
                    emit({"state": "REFINED", "round": round_idx,
                                  "new_tags": plan.algorithm_tags,
                                  "kept_best_pass": best_pass})
                    round_idx += 1  # while 循环需显式递增（原 for 由迭代器处理）
                    continue
                except Exception as e:  # noqa: BLE001
                    emit({"state": "REFINED", "round": round_idx, "warn": f"refine failed: {e}"})

            # 并行修复池中全部候选
            async def fix_one(cand: Solution, results: list[JudgeResult]) -> Solution:
                if not results:
                    return cand  # 无测试点（外部题未解析出标准测试）→ 保持原样，避免 next() 在空序列抛 StopIteration
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
                emit({"state": State.REFLECTED, "round": round_idx, "pool": len(pool)})
            except Exception as e:  # noqa: BLE001
                emit({"state": State.REFLECTED, "round": round_idx, "warn": f"reflect failed: {e}"})
                break
            round_idx += 1

        final = pool[0]
        emit({"state": "FINAL", "code": final.code, "passed": False, "rounds": max_rounds,
              "language_used": final.language.value})
        # 自动模式下，失败后用末轮 verdict 分布诊断"语言/性能问题 vs 算法问题"
        language_advice = ""
        if language is None:
            from collections import Counter

            c = Counter(r.verdict for results in judged for r in results)
            n = sum(c.values()) or 1
            tle, re_, wa = c.get(Verdict.TLE, 0), c.get(Verdict.RE, 0), c.get(Verdict.WA, 0)
            if used_cpp:
                language_advice = "已尝试 Python 与 C++ 均失败，疑似算法/题意问题（非语言原因）"
            elif tle / n > 0.3:
                language_advice = (f"建议重试并指定语言 C++17（--lang cpp）：末轮主要为 TLE({tle}/{n})，"
                                   "疑似 Python 性能瓶颈，C++ 更可能通过")
            elif re_ / n > 0.3:
                language_advice = (f"建议重试并指定语言 C++17（--lang cpp）：末轮主要为 RE({re_}/{n})，"
                                   "疑似递归深度/语言特性，C++ 更稳")
            elif wa / n >= 0.3:
                language_advice = f"算法实现问题（末轮主要为 WA({wa}/{n})），C++ 无法改善"
            else:
                language_advice = "混合失败（WA+RE/TLE），疑似算法主体错误"
        return {"problem_id": problem.id, "difficulty": problem.difficulty,
                "passed": False, "rounds": max_rounds, "code": final.code,
                "language_used": final.language.value,
                "judge": problem.judge.model_dump() if problem.judge else None,
                "language_advice": language_advice,
                "plan": plan.model_dump() if plan else None,
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
