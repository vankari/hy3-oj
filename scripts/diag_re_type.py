"""验证 RE 是否为递归深度超限：跑失败题最终代码，抓 stderr 关键行。"""
import json

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Solution
from hy3_oj.sandbox.docker_executor import DockerExecutor

TARGETS = ["p01288 Marked Ancestor", "p01856 Typhoon", "p01290 Queen's Case"]
recs = {r["problem_id"]: r for r in
        (json.loads(l) for l in open("runs/closed_loop_mid100_v11.jsonl", encoding="utf-8") if l.strip())}

probs = {p.id: p for p in __import__(
    "hy3_oj.data.subset", fromlist=["load_subset"]).load_subset("data/subsets/subset_mid100.jsonl")}

ex = DockerExecutor(load_config())
for pid in TARGETS:
    r = recs.get(pid)
    p = probs.get(pid)
    if not r or not p:
        print(f"{pid}: 缺记录/缺题")
        continue
    tests = (p.public_tests or p.samples or p.private_tests)[:2]
    print(f"\n===== {pid} =====")
    try:
        rs = ex.execute(Solution(code=r["code"]), tests)
        for x in rs:
            print("  verdict:", x.verdict.value)
            # 只看最后几行（异常类型在末尾）
            err = x.stderr.strip().splitlines()
            print("  stderr tail:", err[-3:] if err else "(空)")
    except Exception as e:  # noqa: BLE001
        print("  exec error:", type(e).__name__, e)
ex.close()
