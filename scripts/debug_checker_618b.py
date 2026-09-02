"""调试 618_B 特判：生成 checker → 逐步验证。"""
from __future__ import annotations

import asyncio

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Solution
from hy3_oj.data.subset import load_subset
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox import special_judge
from hy3_oj.sandbox.docker_executor import DockerExecutor


async def main() -> None:
    problems = load_subset("data/subsets/subset_618b.jsonl")
    p = problems[0]
    cfg = load_config()
    client = Hy3Client(cfg)
    executor = DockerExecutor(cfg)

    code = await special_judge.generate_checker(client, p)
    print("=== checker 生成:", "None" if not code else f"{len(code)} chars")
    if not code:
        return
    print(code[:600])

    tests = (p.samples + p.public_tests + p.private_tests)[:5]
    print("=== tests:", len(tests), " ref_solutions:", len(p.reference_solutions))
    ref_outs = executor.run_stdout(Solution(code=p.reference_solutions[0]), [t.input for t in tests])
    print("=== ref_outs:", None if ref_outs is None else [o[:30] for o in ref_outs])

    pairs = [(t.input, o) for t, o in zip(tests, ref_outs)] + [(tests[0].input, "")]
    verdicts = executor.run_checker(code, pairs)
    print("=== run_checker verdicts:", verdicts)

    ok = special_judge.validate_checker(executor, p, code)
    print("=== validate_checker:", ok)
    await client.close()
    executor.close()


asyncio.run(main())
