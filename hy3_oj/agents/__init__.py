"""Agent 编排层：六个职责单一的智能体。

约定：Agent 之间不直接通信，只经 core.schemas 模型由 pipeline 转发，
保证可独立单测、编排层可整体替换（自研 asyncio ↔ tRPC-Agent）。
"""
