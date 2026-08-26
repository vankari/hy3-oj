"""Planner：慢思考产出结构化解题计划（骨架）。

输入 Problem → 输出 Plan（算法选型理由、复杂度证明、边界清单）。
可选挂载相似题 exemplar（MapCoder 式检索增强，检索库须用评测子集外的题防泄漏）。
TODO(D7): 实现 plan(problem) -> Plan。
"""
from __future__ import annotations
