"""Reviewer：过程评估器（任务书核心 R3–R6）。

输入完整解题轨迹 → 输出 ProcessReview。对 AC 与失败样本都运行。

五段式分步审查（错误步骤定位 = 首个 fail 段）：
①题意理解 ②算法选型 ③复杂度论证 ④边界处理 ⑤实现一致性

蒙对检测（规则先行，LLM 复核）：硬编码样例 / 输入特判 / 声称复杂度与实现不符。
LLM 不可用时退化为纯规则审查（process_score 仅由蒙对规则决定）。
"""
from __future__ import annotations

import json
import re

from hy3_oj.core.schemas import (
    GenMode,
    Plan,
    Problem,
    ProcessErrorType,
    ProcessReview,
    ReviewStep,
    Solution,
    StepVerdict,
)
from hy3_oj.llm.client import Hy3Client

_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# ---------- 蒙对检测规则（纯规则，可单测） ----------

def check_hardcoded_samples(solution: Solution, problem: Problem) -> list[str]:
    """规则 1：代码中出现样例输入/输出字面量。"""
    flags: list[str] = []
    for sample in problem.samples:
        for literal in {sample.input.strip(), (sample.expected_output or "").strip()} - {""}:
            if len(literal) >= 4 and literal in solution.code:
                flags.append(f"hardcoded_sample:{literal[:32]}")
    return flags


def check_input_special_case(solution: Solution) -> list[str]:
    """规则 2：输入特判分支，如 `if n == 5: print(...)`。"""
    pattern = re.compile(r"if\s+\w+\s*==\s*\d+\s*:\s*print", re.MULTILINE)
    return [f"special_case:{m.group(0)[:48]}" for m in pattern.finditer(solution.code)]


def check_complexity_mismatch(solution: Solution, plan: Plan | None) -> list[str]:
    """规则 3：Plan 声称多项式级复杂度但实现含可疑深度嵌套循环（启发式）。"""
    if not plan or not plan.time_complexity:
        return []
    claimed = plan.time_complexity.replace(" ", "")
    claims_fast = any(k in claimed for k in ("O(n)", "O(nlogn)", "O(logn)", "O(1)"))
    if not claims_fast:
        return []
    # 统计连续嵌套 for/while 的最大深度（粗略按缩进）
    max_depth = 0
    depth = 0
    for line in solution.code.splitlines():
        stripped = line.strip()
        if stripped.startswith(("for ", "while ")):
            depth += 1
            max_depth = max(max_depth, depth)
        elif stripped and not stripped.startswith(("#", "@")) and depth and len(line) - len(line.lstrip()) == 0:
            depth = 0
    if max_depth >= 3:
        return [f"complexity_mismatch:claimed={plan.time_complexity},nested_loops={max_depth}"]
    return []


def lucky_pass_flags(solution: Solution, problem: Problem, plan: Plan | None) -> list[str]:
    """汇总全部蒙对规则命中项。"""
    return (
        check_hardcoded_samples(solution, problem)
        + check_input_special_case(solution)
        + check_complexity_mismatch(solution, plan)
    )


# ---------- LLM 五段式审查 ----------

_STEPS = [s.value for s in ReviewStep]
_ERROR_TYPES = [e.value for e in ProcessErrorType]


def _extract_json(text: str) -> dict:
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


async def review(
    client: Hy3Client | None,
    problem: Problem,
    plan: Plan | None,
    solution: Solution,
    verdict_summary: str,
) -> ProcessReview:
    """对一条解题轨迹做过程评估。client=None 时仅跑蒙对规则。"""
    flags = lucky_pass_flags(solution, problem, plan)

    if client is None:
        return ProcessReview(
            step_verdicts=[StepVerdict(step=s, passed=True, evidence="规则审查未覆盖") for s in ReviewStep],
            lucky_pass_flags=flags,
            process_score=1.0 if not flags else 0.4,
        )

    plan_text = "无（直出）"
    if plan:
        plan_text = (
            f"算法：{plan.algorithm_tags}\n步骤：{plan.approach}\n"
            f"声称复杂度：{plan.time_complexity}\n边界清单：{plan.edge_cases}"
        )
    user = (
        f"题目：\n{problem.statement[:6000]}\n\n"
        f"解题计划：\n{plan_text}\n\n"
        f"最终代码：\n```python\n{solution.code[:6000]}\n```\n\n"
        f"判题结论：{verdict_summary}\n\n"
        f"对解题过程做五段式审查：{_STEPS}。每段判定 pass/fail 并引用证据；"
        f"错误类型从 {_ERROR_TYPES} 中选。输出 JSON："
        '{"step_verdicts": [{"step": "...", "passed": true, "evidence": "..."}], '
        '"error_step": "首个fail段或null", "error_type": "类型或null", "process_score": 0.0~1.0}'
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是竞赛教练级评审，只输出 JSON。"},
             {"role": "user", "content": user}],
            mode=GenMode.SLOW, temperature=0.0, stage="review",
        )
        data = _extract_json(r.content)
    except Exception:  # noqa: BLE001
        data = {}

    step_verdicts: list[StepVerdict] = []
    for sv in data.get("step_verdicts", []):
        try:
            step_verdicts.append(StepVerdict(
                step=ReviewStep(sv.get("step", ReviewStep.COMPREHENSION.value)),
                passed=bool(sv.get("passed", True)),
                evidence=str(sv.get("evidence", ""))[:300],
            ))
        except ValueError:
            continue
    if not step_verdicts:
        step_verdicts = [StepVerdict(step=s, passed=True, evidence="LLM 审查未返回，默认通过") for s in ReviewStep]

    error_step = None
    if data.get("error_step"):
        try:
            error_step = ReviewStep(data["error_step"])
        except ValueError:
            error_step = None
    error_type = None
    if data.get("error_type"):
        try:
            error_type = ProcessErrorType(data["error_type"])
        except ValueError:
            error_type = None

    try:
        score = float(data.get("process_score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    if flags:
        score = min(score, 0.4)  # 蒙对规则命中时封顶

    return ProcessReview(
        step_verdicts=step_verdicts,
        error_step=error_step,
        error_type=error_type,
        lucky_pass_flags=flags,
        process_score=max(0.0, min(1.0, score)),
    )
