"""端到端验证 Hy3Client：真实调用 + 快/慢模式 + 缓存命中 + 计量落盘。"""
from __future__ import annotations

import asyncio

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import GenMode
from hy3_oj.llm.client import Hy3Client
from hy3_oj.llm.pricing import summarize


async def main() -> None:
    cfg = load_config()
    client = Hy3Client(cfg)
    msgs = [{"role": "user", "content": "只输出一个整数：3*7=?"}]

    slow = await client.chat(msgs, mode=GenMode.SLOW, stage="smoke")
    print(f"[slow] answer={slow.content.strip()!r} reasoning_tokens={slow.reasoning_tokens} has_reasoning={bool(slow.reasoning)}")

    fast = await client.chat(msgs, mode=GenMode.FAST, stage="smoke")
    print(f"[fast] answer={fast.content.strip()!r} reasoning_tokens={fast.reasoning_tokens} has_reasoning={bool(fast.reasoning)}")

    again = await client.chat(msgs, mode=GenMode.SLOW, stage="smoke")
    print(f"[cache-hit] {again.cached}")

    print("metering:", summarize())
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
