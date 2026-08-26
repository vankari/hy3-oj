"""过程评估器有效性验证（骨架，任务书 R7）。

- 定位准确率：取官方参考解，规则+LLM 自动注入已知 bug（改边界/换错算法/删取模），
  注入位置为 ground truth；Reviewer 预测 error_step 与之比对，段级命中率目标 ≥70%。
- 误报率：官方正确参考解上跑 Reviewer，被判过程有问题的样本人工抽检（~50 题），
  区分真实问题 vs 误报，目标 ≤20%；抽检记录落盘（题号/判定/理由/抽检人）。
TODO(D11): 实现 inject_bugs(solution) 与 evaluate_localization(subset)。
"""
from __future__ import annotations
