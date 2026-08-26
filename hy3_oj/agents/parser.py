"""Parser：题意结构化 + 算法标签预测（骨架）。

输入原始题面 → 输出 Problem + tags。快思考；长题面一次读入（256K 上下文）；
标签集合对齐 CodeContests 官方 tag 体系，供 planner 路由与相似题检索。
TODO(D7): 实现 parse(raw_statement) -> Problem。
"""
from __future__ import annotations
