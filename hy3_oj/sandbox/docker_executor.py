"""Docker SDK 一次性容器执行器（骨架）。

镜像 python:3.11-slim（C++17 阶段加 gcc 镜像）；代码只读挂载；
nano_cpus/mem_limit/网络 none/超时强杀；容器池并发上限可配；
Windows 路径 resolve() 后统一映射容器 POSIX 路径。
与 cube_adapter 同一协议：execute(solution, tests) -> list[JudgeResult]。
TODO(D4): 实现 DockerExecutor（需 Docker Desktop 运行中）。
"""
from __future__ import annotations

from hy3_oj.core.schemas import JudgeResult, Solution, TestCase


class DockerExecutor:
    """容器内限时/限内存执行（待实现）。"""

    def __init__(self, config: dict) -> None:
        self.config = config["sandbox"]

    def execute(self, solution: Solution, tests: list[TestCase]) -> list[JudgeResult]:
        raise NotImplementedError("D4 实现：docker SDK 起一次性容器判题")
