"""批量评测驱动（骨架）。

asyncio 并发：采样 × 判题双管道；容器池上限见 configs.sandbox.container_pool；
每题结果与轨迹落盘 runs/，支持断点续跑。
TODO(D11): 实现 run_subset(subset, pipeline) -> records。
"""
from __future__ import annotations
