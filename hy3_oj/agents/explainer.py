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

from hy3_oj.core.schemas import GenMode, Plan, Problem, ProcessReview, Solution
from hy3_oj.llm.client import Hy3Client

_SYSTEM = (
    "你是一位善于教学的算法竞赛教练。你的读者是刚学算法的初学者："
    "讲解要由浅入深、先讲为什么再讲怎么做，避免堆砌术语，关键处给出直觉解释。"
)

_OUTLINE = """请按以下结构输出 Markdown 题解（不要输出推理过程，直接成文）：

## 1. 题目在说什么
（用自己的话重述题意，明确输入、输出、数据范围；指出约束里最关键的量级）

## 2. 从暴力想到正解
（先说最朴素的做法与它为什么慢，再说如何优化，讲清"为什么能想到这个算法"）

## 3. 算法步骤
（编号步骤，与代码结构一一对应）

## 4. 为什么这样做是对的
（不变量/归纳/反证，简短说清即可）

## 5. 复杂度
（时间复杂度与空间复杂度，给出推导过程，并说明能否通过数据范围）

## 6. 代码讲解
（按代码关键片段讲解，说明每个变量/循环在做什么）

## 7. 易错点
（边界情况、溢出、输入输出格式等初学者常踩的坑）
"""


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
            f"未通过步骤段：{fails or '无'}"
        )

    user = (
        f"题目：\n{problem.statement[:6000]}\n\n"
        f"约束：{problem.constraints or '见题面'}\n\n"
        f"解题计划：\n{plan_text}\n\n"
        f"最终{language_hint}代码：\n```\n{solution.code[:6000]}\n```\n\n"
        f"判题结论：{judge_summary}{review_text}\n\n"
        f"{_OUTLINE}\n\n"
        "注意：若判题未通过或过程审查发现问题，请在第 7 节明确指出"
        "本题曾出现的具体错误与修复思路，帮助初学者避开同类陷阱。"
    )

    r = await client.chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        mode=GenMode.FAST, temperature=0.3, max_tokens=8192, stage="explain",
    )
    return (r.content or "").strip()
