"""CubeSandbox 适配接口（占位）。

与 docker_executor 同一 execute(solution, tests) -> list[JudgeResult] 协议，
CubeSandbox（E2B 兼容 SDK，60ms 建沙箱）实现后置接入，配置热替换。
TODO(stretch): 调研 CubeSandbox SDK 并实现。
"""
from __future__ import annotations
