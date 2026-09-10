"""Explainer：面向初学者的文字题解生成器。

补齐当前系统缺口：已有 Plan（要点）、代码、错误定位，但**缺少可供人阅读的成文题解**
（任务书 R1 要求"产出完整解答过程，而非仅输出最终答案"）。

生成结构（markdown）：
1. 题目重述（用自己的话，明确输入/输出/约束）
2. 思路引导（从暴力到优化，讲清"为什么想到这个算法"）
3. 算法步骤（编号步骤，对应代码结构）
4. 正确性说明（不变量 / 归纳 / 反证，简短）
5. 复杂度分析（时间/空间，含推导）
6. 代码讲解（按代码块讲解关键点）
7. 易错点与边界（n=0/1、极值、溢出、输入输出格式）

设计要点：
- 用快思考（慢思考 CoT 会被 max_tokens 截断，见 planner 教训）
- 输入包含判题轨迹与过程审查结论：让题解能回应"这题错在哪"（闭环价值）
"""
from __future__ import annotations

from pathlib import Path

import yaml

from hy3_oj.core.schemas import GenMode, Plan, Problem, ProcessReview, Solution
from hy3_oj.llm.client import Hy3Client

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "explainer.yaml"
_PROMPT = yaml.safe_load(_PROMPT_PATH.read_text(encoding="utf-8"))
_SYSTEM = _PROMPT["system"]
_OUTLINE = _PROMPT["outline"]


async def explain(
    client: Hy3Client,
    problem: Problem,
    solution: Solution,
    plan: Plan | None = None,
    review: ProcessReview | None = None,
    judge_summary: str = "",
    language_hint: str = "Python3",
) -> str:
    """生成面向初学者的文字题解（markdown 文本）。"""
    plan_text = "（无，直出）"
    if plan:
        plan_text = (
            f"算法标签：{plan.algorithm_tags}\n"
            f"要点：{plan.approach}\n"
            f"声称复杂度：{plan.time_complexity}\n"
            f"边界清单：{plan.edge_cases}"
        )

    # 过程审查结论：让题解能回应"错在哪 / 蒙对没"
    review_text = ""
    if review is not None:
        fails = [sv.step.value for sv in review.step_verdicts if not sv.passed]
        review_text = (
            f"\n过程审查：error_step={review.error_step.value if review.error_step else '无'}，"
            f"error_type={review.error_type.value if review.error_type else '无'}，"
            f"蒙对标记={review.lucky_pass_flags or '无'}\n"
            f"未通过步骤段：{fails or '无'}\n"
            f"完整审查证据：{review.model_dump_json()}"
        )

    user = (
        f"题目：\n{problem.statement[:6000]}\n\n"
        f"约束：{problem.constraints or '见题面'}\n\n"
        f"解题计划：\n{plan_text}\n\n"
        f"最终{language_hint}代码：\n```\n{solution.code[:6000]}\n```\n\n"
        f"判题结论：{judge_summary}{review_text}\n\n"
        f"{_OUTLINE}\n\n"
    )

    r = await client.chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        mode=GenMode.FAST, temperature=0.3, max_tokens=8192, stage="explain",
    )
    return (r.content or "").strip()
