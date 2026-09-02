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


async def plan_diverse(client: Hy3Client, problem: Problem, n: int = 3) -> list[Plan]:
    """产出 n 个不同算法范式的 Plan（AlphaCode 思路：覆盖多种正确解法，避免单 plan 路径锁定）。

    让模型一次列 n 种可行算法范式并各自给出要点计划；解析失败时回退单个 plan()。
    用于 medium/hard 档：多种思路分别采样代码，预筛后取最优（90+ 攻坚关键）。
    """
    samples = "\n".join(f"输入：\n{t.input}\n输出：\n{t.expected_output or ''}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:8000]}\n\n"
        f"约束：{problem.constraints or '见题面'}\n\n样例：\n{samples}\n\n"
        f"列出 {n} 种**不同的**可行算法范式（如 暴力/贪心/DP/二分/数据结构/数学 等不同角度），"
        "每种给出要点化计划。直接输出 JSON 数组（不要推理过程）："
        "[{\"algorithm_tags\": [...], \"approach\": [要点步骤], "
        "\"time_complexity\": \"O(...)\", \"space_complexity\": \"O(...)\", "
        "\"edge_cases\": [...]}, ...]"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是算法竞赛教练，只输出 JSON 数组。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.4, max_tokens=8192, stage="plan_diverse",
        )
        items = _extract_json_list(r.content)
    except Exception:  # noqa: BLE001
        items = []
    plans = [
        Plan(
            algorithm_tags=list(d.get("algorithm_tags", [])),
            approach=list(d.get("approach", [])),
            time_complexity=str(d.get("time_complexity", "")),
            space_complexity=str(d.get("space_complexity", "")),
            edge_cases=list(d.get("edge_cases", [])),
        )
        for d in items if isinstance(d, dict) and d.get("approach")
    ]
    if not plans:  # 回退单 plan
        plans = [await plan(client, problem)]
    return plans[:n]


_JSON_LIST_RE = re.compile(r"\[.*\]", re.DOTALL)


def _extract_json_list(text: str) -> list:
    m = _JSON_LIST_RE.search(text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def deep_analyze(client: Hy3Client, problem: Problem) -> str:
    """慢思考自由文本深分析（hard 档增强）：算法讨论、陷阱、复杂度论证。

    慢思考适合自由文本推理（CoT 即产出）；与结构化输出相反，不要求 JSON。
    产出作为上下文注入 Planner/Coder，提升 hard 题规划质量（提升空间 #1）。
    """
    samples = "\n".join(f"输入：\n{t.input}\n输出：\n{t.expected_output or ''}" for t in problem.samples[:2])
    user = (
        f"题目：\n{problem.statement[:8000]}\n\n"
        f"约束：{problem.constraints or '见题面'}\n\n样例：\n{samples}\n\n"
        "请深入分析这道题：1) 问题的本质结构与关键观察；2) 候选算法对比与最终选择理由；"
        "3) 复杂度推导（代入数据范围验算）；4) 容易出错的边界与实现陷阱。"
        "自由文本输出，不需要代码。"
    )
    r = await client.chat(
        [{"role": "system", "content": "你是算法竞赛教练，做深度题目分析。"},
         {"role": "user", "content": user}],
        mode=GenMode.SLOW, temperature=0.6, max_tokens=8192, stage="deep_analysis",
    )
    return r.content
