"""CodeContests 加载器（骨架，评测基准第一优先级）。

HF deepmind/code_contests：description→statement；public/private/generated_tests
直接可用（本地判题完全可控）；cf_rating/difficulty 字段作难度分层依据（任务书 R2）；
solutions 字段的官方参考解用于 bug 注入验证（任务书 R7）。
TODO(D2): 实现 load(split) -> Iterator[Problem]；字段映射与空测试过滤。
"""
from __future__ import annotations
