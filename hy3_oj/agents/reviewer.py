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

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

RULE_VERSION = "0.5"  # 审查版本（v0.5：LLM 语义审查 + 行为探针双层；探针见 agents/prober.py）

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

_STEPS = [s.value for s in ReviewStep]
_ERROR_TYPES = [e.value for e in ProcessErrorType]

# 五段定义与归属规则（v0.2：消除"边界处理 vs 实现一致性"等相邻段歧义，修复定位准确率 33% 缺口）
_STEP_DEFINITIONS = """\
五段定义与归属规则（判 fail 前必须先对照定义确认归属）：
1. 题意理解：对题目目标、输入输出含义、约束范围的理解。读错题意（如目标函数理解反、约束范围看错）属此段。
2. 算法选型：算法、数据结构或求解方向的选择。该用 DP 却用贪心、排序方向弄反、求解方向整体反转——典型表现为把 max 写成 min 或把 min 写成 max、把升序写成降序——属此段（不归边界处理或实现一致性）。
3. 复杂度论证：复杂度分析本身。声称的量级与实现实际量级不符、数值代入论证错误（如代入约束后超出时限仍声称可过），属此段。
4. 边界处理：输入数据边界条件的处理。off-by-one（如 range(n) 写成 range(n-1) 漏掉末元素）、比较符取等错误（<= 写成 <）、n=0/1、空输入、极端规模输入未处理，属此段。注意：本段"极值"指输入数据的极端取值；代码中 max/min 函数写反不是边界问题，归算法选型。
5. 实现一致性：代码与算法意图的一致性。运算符笔误（+ 写成 -）、变量名/下标写错、实现与计划步骤矛盾，属此段。注意：max/min 写反属求解方向整体反转，归算法选型而非本段。"""

_JUDGE_RULES = """\
判定要求：
- 每段判 pass/fail；fail 的 evidence 必须包含：出错代码的行号 + 该行错在哪 + 为何归属于该段（对照上方定义）。
- 判 fail 必须指向具体行的具体错误（该行实际行为 vs 应有行为）；没有行级证据时不许凭整体风格或"我会用别的算法"判 fail。
- 评估锚点是题面、判题预期输出与最终代码本身：**解题计划只是早期草稿，不是 ground truth**
  （编码/修复阶段可能推翻了错误计划）。计划与实现不一致本身不构成任何段的 fail；
  只有当最终代码的逻辑本身不成立时才判 fail。
- 声称代码行为错误时，尽量附上一个具体输入佐证该行行为与应有行为不符（不强制）；
  代码写得丑、写法与计划不同、存在无行为影响的死代码，都不构成 fail。
- 归属判定按错误的**机制**（该行代码本身错在哪），而非**后果**（在什么输入下暴露、导致什么现象）。
  例：表达式内 + 写成 -，即使只在边界输入下才暴露，仍归实现一致性；
  循环上界少迭代一次，即使后果是整个答案错误，仍归边界处理。
- error_step = 五段顺序中首个 fail 段，即根本原因所在段，而非后续症状段
  （例：边界遗漏导致实现层面结果错误，error_step 应为"边界处理"）。
- process_score 取 0.0~1.0。"""


def _extract_json(text: str) -> dict:
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


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
) -> ProcessReview:
    """对一条解题轨迹做过程评估。

    client=None 时只出静态信号（不定罪）；executor 提供且 answer_passed=True 时
    追加行为探针（题面官方样例 + 参考解反向校验，行为级蒙对铁证，见 prober.py）。
    """
    signals = lucky_pass_signals(solution, problem, plan)

    # 行为探针：仅对 AC 解运行（R6 场景；失败解的过程问题已由判题证实）
    probe_flags: list[str] = []
    if executor is not None and answer_passed:
        try:
            from hy3_oj.agents import prober

            probe_flags = await prober.probe(client, executor, problem, solution) if client else []
        except Exception as e:  # noqa: BLE001
            logging.warning("行为探针异常 %s: %s", problem.id, e)

    if client is None:
        # 纯规则降级模式：信号只记入证据，不定罪（v0.2 教训：表面模式无铁证）
        evidence = "规则审查未覆盖"
        if signals or probe_flags:
            evidence = f"静态信号(未复核): {'; '.join(signals + probe_flags)}"
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
    user = (
        f"题目：\n{problem.statement[:6000]}\n\n"
        f"判题样例（含数据集预期输出，格式判定以此为准）：\n{samples_text}\n\n"
        f"解题计划（早期草稿，仅供参考，不是 ground truth）：\n{plan_text}\n\n"
        f"最终代码（含行号）：\n```python\n{_number_lines(solution.code[:6000])}\n```\n\n"
        f"判题结论：{verdict_summary}\n\n"
        f"{signals_block}"
        f"对解题过程做五段式审查：{_STEPS}。\n{_STEP_DEFINITIONS}\n\n{_JUDGE_RULES}\n"
        f"error_type 从 {_ERROR_TYPES} 中选。\n"
        "输出 JSON："
        '{"step_verdicts": [{"step": "...", "passed": true, "evidence": "行号+错因+归属依据"}], '
        '"error_step": "首个fail段或null", "error_line": 出错行号或null, '
        '"error_type": "类型或null", "process_score": 0.0~1.0'
        f"{signals_schema}" + "}"
    )
    # 快思考：慢思考输出是 CoT 会被截断，到不了 JSON（v1 planner 同根因，实测踩坑）
    data: dict = {}
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是竞赛教练级评审，只输出 JSON。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.0, max_tokens=4096, stage="review",
        )
        data = _extract_json(r.content)
        if not data:
            logging.warning("Reviewer LLM 返回无法解析（content 前 100 字符）: %s", r.content[:100])
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

    # 定罪来源：①静态信号经 LLM 复核确认 ②行为探针（机器验证，无需 LLM 复核）
    flags = _confirm_signals(data, signals) + probe_flags

    try:
        score = float(data.get("process_score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    if flags:
        score = min(score, 0.4)  # 蒙对命中（LLM 确认信号或探针铁证）时封顶

    # 探针命中但未被判出任何 fail 段时，把行为证据落到实现一致性段（保证可追溯）
    if probe_flags and error_step is None:
        error_step = ReviewStep.IMPL_CONSISTENCY
        error_type = error_type or ProcessErrorType.IMPL
        step_verdicts = [
            StepVerdict(step=sv.step, passed=False if sv.step == ReviewStep.IMPL_CONSISTENCY else sv.passed,
                        evidence=probe_flags[0][:300] if sv.step == ReviewStep.IMPL_CONSISTENCY else sv.evidence)
            for sv in step_verdicts
        ]

    return ProcessReview(
        step_verdicts=step_verdicts,
        error_step=error_step,
        error_type=error_type,
        lucky_pass_flags=flags,
        process_score=max(0.0, min(1.0, score)),
    )
