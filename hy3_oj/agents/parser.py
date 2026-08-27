"""Parser：题意结构化 + 算法标签预测（快思考）。

长题面一次读入（256K 上下文）；标签对齐 CodeContests tag 体系，供 planner 路由与相似题检索。
LLM 失败时回退为原样题面 + 空标签，保证闭环不中断。
"""
from __future__ import annotations

import json
import re

from hy3_oj.core.schemas import GenMode, Problem
from hy3_oj.llm.client import Hy3Client

TAGS = ["dp", "greedy", "graph", "math", "data_structures", "strings", "number_theory",
        "geometry", "brute_force", "binary_search", "constructive", "sortings",
        "two_pointers", "dfs_and_similar", "trees", "shortest_paths", "bitmasks", "combinatorics"]

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


async def parse(client: Hy3Client, problem: Problem) -> Problem:
    """结构化题面并预测标签；返回更新后的 Problem（不破坏原测试数据）。"""
    user = (
        "将以下竞赛题面结构化为 JSON："
        '{"constraints": "数据范围与约束", "io_format": "输入输出格式说明", '
        f'"tags": [从 {TAGS} 中选 1~4 个], "core_requirement": "一句话题意"}}\n\n'
        f"题面：\n{problem.statement[:8000]}"
    )
    r = await client.chat(
        [{"role": "system", "content": "你是算法竞赛题面解析器，只输出 JSON。"},
         {"role": "user", "content": user}],
        mode=GenMode.FAST, temperature=0.0, stage="parse",
    )
    data = _extract_json(r.content)
    tags = [t for t in data.get("tags", []) if t in TAGS]
    constraints = data.get("constraints", "")
    if data.get("core_requirement"):
        constraints = f"{data['core_requirement']}\n{constraints}".strip()
    return problem.model_copy(update={
        "constraints": constraints or problem.constraints,
        "tags": tags or problem.tags,
    })
