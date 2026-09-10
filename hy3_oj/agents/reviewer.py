"""Reviewer：过程评估器（任务书核心 R3–R6）。

输入完整解题轨迹 → 输出 ProcessReview。对 AC 与失败样本都运行。

五段式分步审查（错误步骤定位 = 首个 fail 段）：
①题意理解 ②算法选型 ③复杂度论证 ④边界处理 ⑤实现一致性

蒙对检测（v0.3 起：规则出信号，LLM 定罪）：
- 全部静态规则只产出**候选信号**（硬编码样例 / 输入特判 / 复杂度不符），
  必须经 LLM 结合题意与 Plan 复核 confirmed 才进 lucky_pass_flags 并封顶分数；
- v0.1 教训：静态嵌套深度单独触发 → 误报率 100%（2/2）；
  v0.2 教训：硬规则同样有系统性误报——"First/Second/Impossible" 等输出词汇、
  题目常数界、合法边界分支（if m == 0: print 0）都会被表面模式误中。
  结论：**没有任何表面模式是铁证**，规则负责召回，LLM 负责判定。
LLM 不可用时退化为纯信号审查（只记录信号，不定罪、不封顶）。
"""
from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path

import yaml

from hy3_oj.core.schemas import (
    GenMode,
    Plan,
    Problem,
    ProcessErrorType,
    ProcessReview,
    ReviewStep,
    Solution,
    StepVerdict,
    ReviewMaterial,
)
from hy3_oj.core.assessment import explanation_hash
from hy3_oj.llm.client import Hy3Client

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

RULE_VERSION = "0.7"  # 题解与轨迹审查；不执行测试，不决定最终结果

# ---------- AST 有效嵌套循环深度 ----------

# range(≤32 的整数字面量) 视为常数因子循环，不计入有效深度
_CONST_BOUND_THRESHOLD = 32


def _is_small_constant_bound(loop: ast.AST) -> bool:
    """for i in range(<整数字面量界>) 且规模 ≤ 阈值 → 常数因子（如三重循环 each range(3)）。"""
    if not isinstance(loop, ast.For):
        return False
    call = loop.iter
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "range"
        and call.args
        and all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in call.args)
    ):
        return False
    vals = [a.value for a in call.args]  # type: ignore[attr-defined]
    if len(vals) == 1:
        count = vals[0]
    elif len(vals) == 2:
        count = vals[1] - vals[0]
    else:
        count = (vals[1] - vals[0]) // max(abs(vals[2]), 1)
    return count <= _CONST_BOUND_THRESHOLD


def _max_effective_loop_depth(code: str) -> int:
    """AST 最大有效嵌套循环深度（常数小界循环不计；语法错误返回 0）。

    v0.1 按行缩进统计，会把顺序出现的循环误计为嵌套，且无法识别常数界；
    两例误报（1250_B 嵌套 5 / 1149_B 嵌套 9 但量级可过）均由此产生。
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return 0

    def visit(node: ast.AST, depth: int) -> int:
        best = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                inc = 0 if _is_small_constant_bound(child) else 1
                best = max(best, visit(child, depth + inc))
            else:
                best = max(best, visit(child, depth))
        return best

    return visit(tree, 0)


# ---------- 蒙对检测：静态信号（候选证据，须 LLM 复核定罪） ----------

def hardcoded_sample_signals(solution: Solution, problem: Problem) -> list[str]:
    """信号 1：代码中出现样例输入/输出字面量。

    注意系统性误报：题目的输出词汇（First/Second/Impossible/DRAW 等）与常数界
    （如 -2000000000）是正确解的合法组成部分，故仅作候选信号交 LLM 判定。
    """
    flags: list[str] = []
    for sample in problem.samples:
        for literal in {sample.input.strip(), (sample.expected_output or "").strip()} - {""}:
            if len(literal) >= 4 and literal in solution.code:
                flags.append(f"hardcoded_sample:{literal[:32]}")
    return flags


def special_case_signals(solution: Solution) -> list[str]:
    """信号 2：输入特判形分支，如 `if n == 5: print(...)`（合法边界处理也长这样）。"""
    pattern = re.compile(r"if\s+\w+\s*==\s*\d+\s*:\s*print", re.MULTILINE)
    return [f"special_case:{m.group(0)[:48]}" for m in pattern.finditer(solution.code)]


def lucky_pass_signals(solution: Solution, problem: Problem, plan: Plan | None) -> list[str]:
    """全部静态信号汇总（仅候选证据；confirmed 靠 LLM，见 review()）。"""
    return (
        hardcoded_sample_signals(solution, problem)
        + special_case_signals(solution)
        + complexity_signals(solution, plan)
    )


# ---------- 蒙对检测：弱信号（不单独定罪，须 LLM 复核） ----------

def complexity_signals(solution: Solution, plan: Plan | None) -> list[str]:
    """弱信号：Plan 声称线性/对数级复杂度，但实现有效嵌套循环深度 ≥3。

    仅为静态上限证据，可能误报（内层循环实际迭代很少、或 Plan 已数值论证可过），
    因此不直接进 lucky_pass_flags，由 LLM 结合 Plan 论证与数据范围复核确认。
    """
    if not plan or not plan.time_complexity:
        return []
    claimed = plan.time_complexity.replace(" ", "")
    claims_fast = any(k in claimed for k in ("O(n)", "O(nlogn)", "O(logn)", "O(1)"))
    if not claims_fast:
        return []
    depth = _max_effective_loop_depth(solution.code)
    if depth >= 3:
        return [f"complexity_suspect:claimed={plan.time_complexity},effective_nested_loops={depth}"]
    return []


# ---------- LLM 五段式审查 ----------

_PROMPT = yaml.safe_load((Path(__file__).resolve().parents[1] / "prompts" / "reviewer.yaml").read_text(encoding="utf-8"))


def _extract_json(text: str) -> dict:
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _consistent_review(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    rows = data.get("step_verdicts")
    if not isinstance(rows, list) or len(rows) != len(ReviewStep):
        return False
    if any(not isinstance(row, dict) or type(row.get("passed")) is not bool
           or not isinstance(row.get("step"), str) for row in rows):
        return False
    by_step = {row.get("step"): row for row in rows}
    if set(by_step) != {step.value for step in ReviewStep}:
        return False
    first_fail = next((step.value for step in ReviewStep if not by_step[step.value]["passed"]), None)
    if data.get("error_step") != first_fail:
        return False
    try:
        score = float(data["process_score"])
    except (KeyError, TypeError, ValueError):
        return False
    if not 0 <= score <= 1 or (first_fail and score == 1):
        return False
    return data.get("error_type") in {e.value for e in ProcessErrorType} if first_fail else data.get("error_type") is None


def _number_lines(code: str) -> str:
    """给代码加行号，供 LLM 引用行级证据（v0.2 定位修复）。"""
    return "\n".join(f"{i:>3}: {line}" for i, line in enumerate(code.splitlines(), 1))


def _confirm_signals(data: dict, signals: list[str]) -> list[str]:
    """解析 LLM 对弱信号的复核结论，返回被确认的项（confirmed 才定罪）。"""
    verdicts = data.get("flag_verdicts") or []
    confirmed: list[str] = []
    by_signal = {str(v.get("signal", "")): v for v in verdicts if isinstance(v, dict)}
    for sig in signals:
        v = by_signal.get(sig)
        # LLM 未回应该信号 → 不定罪（宁缺毋滥，弱信号默认 reject）
        if v and v.get("confirmed") is True:
            confirmed.append(f"{sig} (LLM确认: {str(v.get('reason', ''))[:80]})")
    return confirmed


async def review(
    client: Hy3Client | None,
    problem: Problem,
    plan: Plan | None,
    solution: Solution,
    verdict_summary: str,
    executor=None,
    answer_passed: bool | None = None,
    material: ReviewMaterial | None = None,
) -> ProcessReview:
    """对一条解题轨迹做过程评估。

    material 包含最终题解及可见解题轨迹。代码用于核对实现一致性。
    verdict_summary/executor/answer_passed 仅保留旧调用兼容，不影响审查，也不运行测试。
    """
    signals = lucky_pass_signals(solution, problem, plan)

    if client is None:
        # 纯规则降级模式：信号只记入证据，不定罪（v0.2 教训：表面模式无铁证）
        evidence = "规则审查未覆盖"
        if signals:
            evidence = f"静态信号(未复核): {'; '.join(signals)}"
        return ProcessReview(
            step_verdicts=[StepVerdict(step=s, passed=True, evidence=evidence) for s in ReviewStep],
            lucky_pass_flags=[],
            process_score=1.0,
        )

    plan_text = "无（直出）"
    if plan:
        plan_text = (
            f"算法：{plan.algorithm_tags}\n步骤：{plan.approach}\n"
            f"声称复杂度：{plan.time_complexity}\n边界清单：{plan.edge_cases}"
        )
    # 判题样例（含数据集预期输出）：格式类判定必须以此为准，而非仅题面文本
    samples_text = "无"
    if problem.samples:
        parts = []
        for s in problem.samples[:3]:
            parts.append(f"输入：\n{s.input[:300]}\n预期输出：\n{(s.expected_output or '')[:300]}")
        samples_text = "\n---\n".join(parts)
    signals_block = ""
    signals_schema = ""
    if signals:
        signals_block = (
            "静态分析可疑信号（需逐条复核，仅当确实构成蒙对/过程不成立才 confirmed=true）：\n"
            + "\n".join(f"- {s}" for s in signals)
            + "\n复核指引（按信号类型）：\n"
            "- hardcoded_sample：若该字面量是题目要求的输出词汇（如 YES/NO/First/Second/Impossible/"
            "DRAW/WRONG_ANSWER）或题目给定的常数界，正确解也必须包含 → confirmed=false；"
            "仅当代码对样例输入做字面量匹配、直接输出样例答案而非通用求解时才 true。\n"
            "- special_case：若该分支是合法边界处理（如 n==0 时答案为 0）→ confirmed=false；"
            "仅当对特定输入值返回与通用逻辑无关的预谋答案时才 true。\n"
            "- complexity_suspect：若 Plan 已数值论证复杂度可过、或内层循环实际迭代极少 → "
            "confirmed=false；仅当实现实际量级确实超出声称且会导致超时风险才 true。\n\n"
        )
        signals_schema = (
            ', "flag_verdicts": [{"signal": "原文照抄", "confirmed": true/false, "reason": "理由"}]'
        )
    context = {
        "problem": problem.statement[:6000], "samples": samples_text,
        "plan": plan_text, "solution_numbered": _number_lines(solution.code[:6000]),
        "judge_result": verdict_summary, "signals_block": signals_block,
        "signals_schema": signals_schema,
        "explanation_numbered": _number_lines(material.explanation) if material else "未提供成文题解，仅审查给定的计划与过程材料",
        "trace_events": json.dumps(material.trace_events, ensure_ascii=False) if material else "[]",
    }
    user = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: context[m.group(1)], _PROMPT["user"])
    # 快思考：慢思考输出是 CoT 会被截断，到不了 JSON（v1 planner 同根因，实测踩坑）
    data: dict = {}
    try:
        messages = [{"role": "system", "content": _PROMPT["system"]},
                    {"role": "user", "content": user}]
        for attempt in range(2):
            r = await client.chat(messages, mode=GenMode.FAST, temperature=0.0,
                                  max_tokens=4096, stage="review")
            data = _extract_json(r.content)
            if _consistent_review(data):
                break
            messages += [{"role": "assistant", "content": r.content},
                         {"role": "user", "content": _PROMPT["consistency_retry"]}]
        else:
            raise ValueError("Reviewer 返回的逐段判定与汇总结论不一致或不完整，无法确认审查结论")
    except Exception as e:  # noqa: BLE001
        # 额度耗尽/网络错误时显式告警（此前 except+data={} 静默吞错导致全部"默认通过"）
        logging.error("Reviewer LLM 调用失败: %s: %s", type(e).__name__, e)
        raise  # 过程评估是核心交付，LLM 不可用时应显式失败而非产出误导性的"全部通过"

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

    flags = _confirm_signals(data, signals)

    try:
        score = float(data.get("process_score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    if flags:
        score = min(score, 0.4)  # 蒙对命中（LLM 确认信号或探针铁证）时封顶

    return ProcessReview(
        step_verdicts=step_verdicts,
        error_step=error_step,
        error_type=error_type,
        lucky_pass_flags=flags,
        process_score=max(0.0, min(1.0, score)),
        explanation_sha256=explanation_hash(material.explanation) if material and material.explanation else None,
    )
