"""token 成本计量（骨架）。

按题/阶段聚合 token 与耗时，落盘 runs/metering.jsonl，
供"推理深度–通过率–token 成本"帕累托前沿分析（重点技术 1）。
TODO(D1): 定义计量事件 schema 与聚合查询。
"""
from __future__ import annotations
