"""Reflector：CE/RE/WA/TLE 归因与定向修复（慢思考）。

按首个失败 verdict 分流：
- CE → 编译/语法错误定位，最小修复
- RE → 栈归因（越界/除零/递归深度）
- WA → 先构造反例并手算正确答案，再修复
- TLE → 复杂度重分析，不足则直接换更优算法（非微调常数）
"""
from __future__ import annotations

from hy3_oj.core.schemas import GenMode, JudgeResult, Plan, Problem, Reflection, Solution, Verdict
from hy3_oj.llm.client import Hy3Client
from hy3_oj.agents.coder import extract_code

_SYSTEM = {
    Verdict.CE: "你是调试专家。定位编译/语法错误并给出最小修复。",
    Verdict.RE: "你是调试专家。归因运行时崩溃原因并修复。",
    Verdict.WA: "你是竞赛教练。先构造反例手算正确答案，解释代码从哪一步开始偏离，再修复。",
    Verdict.TLE: "你是算法专家。分析复杂度瓶颈；不足则直接更换更优算法范式而非微调常数。",
}


async def reflect(
    client: Hy3Client,
    problem: Problem,
    plan: Plan | None,
    solution: Solution,
    judge: JudgeResult,
    round_idx: int,
) -> Reflection:
    """对一次失败判题做归因，产出修复指令与修复后代码。"""
    verdict = judge.verdict
    ft = judge.failed_test
    user = (
        f"题目约束：{problem.constraints or '见题面'}\n"
        f"解题计划：{plan.approach if plan else '无'}\n"
        f"当前代码：\n```python\n{solution.code}\n```\n"
        f"判题结果：{verdict.value}\n"
        f"错误输出：{judge.stderr[:800]}\n"
        + (f"失败测试点输入：\n{ft.input[:500]}\n期望：{(ft.expected_output or '')[:300]}\n差异：{judge.diff_excerpt[:400]}\n" if ft else "")
        + "\n输出：归因诊断（≤3 句）→ 修复指令（≤3 条）→ 完整修复后代码（```python 代码块）。"
    )
    # 快思考：慢思考输出是 CoT 会被 max_tokens 截断，到不了修复代码块（实测踩坑）
    r = await client.chat(
        [{"role": "system", "content": _SYSTEM.get(verdict, _SYSTEM[Verdict.WA])},
         {"role": "user", "content": user}],
        mode=GenMode.FAST, temperature=0.2, max_tokens=8192, stage="reflect",
    )
    text = r.content
    fixed_code = extract_code(text)
    # 诊断取代码块前的文本；为空时退化用慢思考轨迹或原文截断
    diagnosis = text.split("```")[0].strip()[:500] or (r.reasoning or "")[:500] or text[:500]
    return Reflection(
        cause_class=verdict,
        diagnosis=diagnosis,
        fix_instruction=diagnosis,  # 诊断与指令合并（模型输出已含）
        round_idx=round_idx,
    ), fixed_code
