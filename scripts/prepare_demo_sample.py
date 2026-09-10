"""复验已通过的 hard 样例，导出完整单题数据并保存可回放的 GUI 对话。

python scripts/prepare_demo_sample.py
不重新生成解法；重新运行数据集测试与 Hy3 过程审查/题解，原始跑批结果保持不变。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import ConversationMessage, Language, Solution, Verdict
from hy3_oj.data.subset import load_subset
from hy3_oj.graph.orchestrator import _postprocess
from hy3_oj.sandbox.docker_executor import DockerExecutor
from hy3_oj.ui.history import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
PID = "atcoder:abc302_f"
TITLE = "集合合并 · LiveCodeBench hard"


async def main():
    out = ROOT / "runs/demo/merge_set"
    out.mkdir(parents=True, exist_ok=True)
    problem = next(p for p in load_subset(ROOT / "data/subsets/subset_lcb_v1.jsonl") if p.id == PID)
    source = ROOT / "runs/closed_loop_lcb60_v10.jsonl"
    result = next(r for r in map(json.loads, source.read_text(encoding="utf-8").splitlines())
                  if r["problem_id"] == PID and r.get("passed"))
    assert problem.difficulty == "hard"
    (out / "problem.jsonl").write_text(problem.model_dump_json() + "\n", encoding="utf-8")
    (out / "solution.py").write_text(result["code"], encoding="utf-8")
    trace = ROOT / result["trace_file"]
    if trace.exists():
        (out / "original_trace.jsonl").write_bytes(trace.read_bytes())
        result["trace_file"] = str(out / "original_trace.jsonl")
    cfg = load_config()
    cfg["sandbox"]["time_limit_s"] = 3  # 原题时间限制
    cfg["sandbox"]["memory_mb"] = 1024
    tests = problem.public_tests + problem.private_tests + problem.generated_tests
    executor = DockerExecutor(cfg)
    try:
        judged = await asyncio.to_thread(executor.execute,
                                        Solution(code=result["code"], language=Language.PYTHON3), tests)
    finally:
        executor.close()
    verification = {"source": problem.source.value, "public": len(problem.public_tests),
                    "private": len(problem.private_tests), "generated": len(problem.generated_tests),
                    "total": len(tests), "passed": sum(r.verdict == Verdict.AC for r in judged),
                    "time_limit_s": 3, "memory_mb": 1024}
    (out / "judge_results.json").write_text(json.dumps({"verification": verification,
        "results": [r.model_dump(mode="json") for r in judged]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verification), flush=True)
    if len(judged) != len(tests) or verification["passed"] != len(tests):
        raise RuntimeError("Previously passed solution failed revalidation; see judge_results.json")
    result["language_used"] = "python3"
    result = await _postprocess(cfg, problem, result)
    result["verification"] = verification
    result["problem_statement"] = problem.statement
    result["replay_note"] = "已有解题结果回放：复用 v10 通过代码，本次重新判题、审查并生成题解。"
    result["source_result"] = str(source.relative_to(ROOT))
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "explanation.md").write_text(result["explanation"], encoding="utf-8")
    store = HistoryStore(ROOT / "runs/ui")
    conversation = store.new(TITLE)
    conversation.messages = [
        ConversationMessage(role="user", content="## 集合合并（Merge Set）\n\n"
            "LiveCodeBench 子集 hard · AtCoder ABC302 F\n\n"
            "原题：https://atcoder.jp/contests/abc302/tasks/abc302_f\n\n" + problem.statement),
        ConversationMessage(role="assistant", meta={"result": result}),
    ]
    store.save(conversation)
    manifest = {"problem_id": PID, "title": TITLE, "difficulty": problem.difficulty,
                "original_result": str(source.relative_to(ROOT)), "verification": verification,
                "conversation_id": conversation.id,
                "url": f"http://localhost:8501/?chat={conversation.id}"}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
