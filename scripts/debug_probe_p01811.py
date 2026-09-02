"""单点验证：p01811 的行为探针应命中（官方样例 AABCC 上 AC 解行为错误）。"""
from __future__ import annotations

import asyncio
import json
import sys

from hy3_oj.agents import prober
from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Solution
from hy3_oj.data.subset import load_subset
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor


async def main() -> None:
    problems = load_subset("data/subsets/subset_mid100.jsonl")
    p = next(x for x in problems if x.id == "p01811 ABC Gene")
    rec = next(
        json.loads(l) for l in open("runs/closed_loop_mid100.jsonl", encoding="utf-8")
        if json.loads(l)["problem_id"] == p.id
    )
    cfg = load_config()
    client = Hy3Client(cfg)
    executor = DockerExecutor(cfg)
    flags = await prober.probe(client, executor, p, Solution(code=rec["code"]))
    print("probe flags:", json.dumps(flags, ensure_ascii=False, indent=2))
    await client.close()
    executor.close()
    sys.exit(0 if flags else 1)


asyncio.run(main())
