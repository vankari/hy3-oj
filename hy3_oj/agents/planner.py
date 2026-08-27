"""Planner：慢思考产出结构化解题计划。

要求输出：算法选型理由、时间/空间复杂度推导、边界清单（n=0/1、极值、重复元素）。
LLM 失败时回退为空 Plan（Coder 将退化为直出）。
"""
from __future__ import annotations

import json
import re

from hy3_oj.core.schemas import GenMode, Plan, Problem
from hy3_oj.llm.client import Hy3Client

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(\{.*?\})```", re.DOTALL)
_JSON_GREEDY_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """优先取 ```json 代码块，退化贪婪匹配首个 {...}。"""
    for pattern in (_JSON_BLOCK_RE, _JSON_GREEDY_RE):
        m = pattern.search(text)
        if not m:
            continue
        candidate = m.group(1) if pattern is _JSON_BLOCK_RE else m.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


async def plan(client: Hy3Client, problem: Problem) -> Plan:
    """产出要点化 Plan（算法选型/复杂度/边界）。

    注意：用快思考（disabled thinking）直接输出 JSON——慢思考模式下模型会把回复
    当 CoT 写，长输出被 max_tokens 截断导致永远到不了 JSON 部分（实测踩坑）。
    结构化的复杂度推导由快思考按模板输出即可满足 Reviewer 审查需要。
    """
    samples = "\n".join(f"输入：\n{t.input}\n输出：\n{t.expected_output or ''}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:8000]}\n\n"
        f"约束：{problem.constraints or '见题面'}\n\n样例：\n{samples}\n\n"
        "直接输出解题计划 JSON（不要输出推理过程）："
        "{\"algorithm_tags\": [...], \"approach\": [要点步骤], "
        "\"time_complexity\": \"O(...)及推导\", \"space_complexity\": \"O(...)\", "
        "\"edge_cases\": [边界清单]}。要求复杂度推导完整、不跳步。"
    )
    r = await client.chat(
        [{"role": "system", "content": "你是算法竞赛教练，只输出 JSON。"},
         {"role": "user", "content": user}],
        mode=GenMode.FAST, temperature=0.2, max_tokens=4096, stage="plan",
    )
    data = _extract_json(r.content)
    return Plan(
        algorithm_tags=list(data.get("algorithm_tags", [])),
        approach=list(data.get("approach", [])),
        time_complexity=str(data.get("time_complexity", "")),
        space_complexity=str(data.get("space_complexity", "")),
        edge_cases=list(data.get("edge_cases", [])),
    )
