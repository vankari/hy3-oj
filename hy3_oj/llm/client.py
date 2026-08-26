"""Hy3 API 唯一出口（骨架）。

职责：OpenAI 兼容客户端；tenacity 指数退避重试；信号量限流；
diskcache 按 (prompt, mode, seed) 缓存省 token；每次调用计量落盘 runs/。
TODO(D1): 实测 Hy3 快/慢思考的模型名与推理参数，写入 configs/default.yaml。
"""
from __future__ import annotations

from hy3_oj.core.schemas import GenMode


class Hy3Client:
    """OpenAI 兼容协议封装（待实现）。

    async def chat(messages, mode: GenMode, temperature, seed) -> str
    """

    def __init__(self, config: dict, api_key: str) -> None:
        self.config = config
        self.api_key = api_key
        self.model_map = {
            GenMode.FAST: config["llm"]["model_fast"],
            GenMode.SLOW: config["llm"]["model_slow"],
        }
