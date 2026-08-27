"""Hy3 API 唯一出口（已实测 TokenHub 端点）。

实测结论（2026-08-26，probe_hy3.py / probe_thinking.py）：
- base_url = https://tokenhub.tencentmaas.com/v1（.env 配置，env 优先）
- model = "hy3"；OpenAI chat.completions 兼容
- 返回含 reasoning_content（慢思考轨迹），usage.completion_tokens_details.reasoning_tokens 单独计量
- 快思考开关：extra_body={"thinking": {"type": "disabled"}} → reasoning_tokens=0

职责：tenacity 指数退避重试；asyncio 信号量限流；diskcache 按 (消息,模式,温度) 缓存省 token；
每次调用经 llm.pricing 计量落盘。所有 Agent 禁止绕过本类直接 new OpenAI client。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from hy3_oj.core.config import get_api_key, get_base_url
from hy3_oj.core.schemas import GenMode


@dataclass
class ChatResult:
    """单次调用结果（content 为最终答案；reasoning 为慢思考轨迹，快思考为 None）。"""

    content: str
    reasoning: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class Hy3Client:
    """OpenAI 兼容异步客户端：重试/限流/缓存/计量。"""

    def __init__(self, config: dict) -> None:
        llm_cfg = config["llm"]
        self.cfg = llm_cfg
        self.model = llm_cfg.get("model", "hy3")
        self.mode_body = {
            GenMode.FAST: llm_cfg.get("fast_extra_body") or {},
            GenMode.SLOW: llm_cfg.get("slow_extra_body") or {},
        }
        import httpx

        # trust_env=False：忽略系统/终端代理变量，TokenHub 为国内端点须直连
        self._client = AsyncOpenAI(
            api_key=get_api_key(config),
            base_url=get_base_url(config),
            timeout=llm_cfg.get("timeout_s", 300),
            max_retries=llm_cfg.get("max_retries", 5),
            http_client=httpx.AsyncClient(trust_env=False, timeout=llm_cfg.get("timeout_s", 300)),
        )
        self._sem = asyncio.Semaphore(llm_cfg.get("concurrency", 8))
        self._cache = self._open_cache(llm_cfg.get("cache_dir"))

    @staticmethod
    def _open_cache(cache_dir: str | None):
        try:
            import diskcache

            Path(cache_dir or "runs/llm_cache").mkdir(parents=True, exist_ok=True)
            return diskcache.Cache(cache_dir or "runs/llm_cache")
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _key(messages: list[dict], mode: GenMode, temperature: float, max_tokens: int) -> str:
        payload = json.dumps(
            {"m": messages, "mode": mode.value, "t": temperature, "mt": max_tokens},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def chat(
        self,
        messages: list[dict[str, str]],
        mode: GenMode = GenMode.FAST,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stage: str = "unknown",
    ) -> ChatResult:
        """单次对话（带缓存与限流）。stage 用于成本归集。"""
        key = self._key(messages, mode, temperature, max_tokens)
        if self._cache is not None and key in self._cache:
            hit = self._cache[key]
            hit.cached = True
            return hit

        async with self._sem:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self.mode_body[mode],
            )
        msg = resp.choices[0].message
        details = getattr(resp.usage, "completion_tokens_details", None) if resp.usage else None
        result = ChatResult(
            content=msg.content or "",
            reasoning=getattr(msg, "reasoning_content", None),
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            reasoning_tokens=getattr(details, "reasoning_tokens", 0) or 0,
        )
        if self._cache is not None:
            self._cache[key] = result
        self._meter(stage, mode, result)
        return result

    @staticmethod
    def _meter(stage: str, mode: GenMode, r: ChatResult) -> None:
        try:
            from hy3_oj.llm.pricing import record

            record(stage=stage, mode=mode.value, prompt_tokens=r.prompt_tokens,
                   completion_tokens=r.completion_tokens, reasoning_tokens=r.reasoning_tokens)
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        await self._client.close()
        if self._cache is not None:
            self._cache.close()
