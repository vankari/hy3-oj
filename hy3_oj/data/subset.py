"""难度分层抽样（骨架）。

按 difficulty 分层 + 固定 seed（configs.data.subset_seed=42）抽样 200~400 题，
落盘 data/subsets/ 保证可复现；抽样报告含各桶数量与来源说明（任务书 R2）。
TODO(D2): 实现 make_subset(problems) 与 save/load。
"""
from __future__ import annotations
