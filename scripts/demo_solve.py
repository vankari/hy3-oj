"""单题展示脚本（demo 录制用，区别于批量判题的 run_solve.py）。

完整走一遍并**把每一步都打印出来**：
  题目解析 -> 算法规划 -> K 路生成 -> 预筛 -> 判题 / 修复 -> 过程评估 -> 题解

三种题目来源：
  1. 外部文件：  --file problems/example_two_sum.md
  2. 外部文本：  --text-file 或直接 --stdin（从标准输入读题面）
  3. 数据集选题：--subset data/subsets/subset_lcb_v1.jsonl --id "leetcode:3252"

输出：
  - 终端：分阶段 rich 报告
  - 文件：--out runs/demo/<id>.md（含代码/判题/过程评估/题解，可直接贴报告）

用法：
    python scripts/demo_solve.py --file problems/example_two_sum.md
    python scripts/demo_solve.py --subset data/subsets/subset_lcb_v1.jsonl --id "leetcode:3252" --out runs/demo/lcb_easy.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，重配置为 utf-8 避免 print 中文/特殊符号崩溃
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from hy3_oj.core.config import load_config
from hy3_oj.core.problem_io import load_problem_file
from hy3_oj.core.schemas import Language, Plan, Solution
from hy3_oj.data.subset import load_subset


def _hr(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def _load_problem(args) -> object:
    if args.file:
        p = load_problem_file(args.file)
        print(f"[题目] 来源：文件 {args.file}")
    elif args.text_file:
        p = load_problem_file(args.text_file)
        print(f"[题目] 来源：文本 {args.text_file}")
    elif args.stdin:
        import sys

        tmp = Path("runs/_stdin_problem.md")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(sys.stdin.read(), encoding="utf-8")
        p = load_problem_file(tmp)
        print("[题目] 来源：标准输入")
    elif args.subset:
        probs = load_subset(args.subset)
        if args.id:
            p = next((x for x in probs if x.id == args.id), None)
            if p is None:
                raise SystemExit(f"未找到题号 {args.id}；可用题号示例：{[x.id for x in probs[:5]]}")
        else:
            p = probs[0]
        print(f"[题目] 来源：数据集 {args.subset}")
    else:
        raise SystemExit("需指定 --file / --text-file / --stdin / --subset 之一")
    return p


def _show_problem(p) -> None:
    _hr("① 题目解析")
    print(f"题号    ：{p.id}")
    print(f"难度    ：{p.difficulty}")
    print(f"标签    ：{p.tags or '（未识别）'}")
    print(f"约束    ：{p.constraints or '（未识别）'}")
    print(f"样例数  ：{len(p.samples)} 组")
    print(f"题面长度：{len(p.statement)} 字符")
    if not p.samples:
        print("  [!] 未识别到样例 -> 判题将无可用测试点，验证强度：弱")
    if p.difficulty == "unknown":
        print("  [!] 未识别难度 -> 按 medium 处理")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--text-file")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--subset")
    ap.add_argument("--id")
    ap.add_argument("--out")
    ap.add_argument("--no-explain", action="store_true", help="跳过题解生成（省额度）")
    ap.add_argument("--no-review", action="store_true", help="跳过过程评估（省额度）")
    ap.add_argument("--lang", choices=["py", "cpp"], default=None,
                    help="显式指定语言；不指定则自动（优先 Python3，失败后可诊断是否建议 C++）")
    args = ap.parse_args()

    target_lang = {"py": Language.PYTHON3, "cpp": Language.CPP17}.get(args.lang)

    p = _load_problem(args)
    _show_problem(p)

    cfg = load_config()
    from hy3_oj.core.pipeline import SolvePipeline

    pipeline = SolvePipeline(cfg)
    t0 = time.time()
    try:
        _hr("② 闭环解题（解析 -> 规划 -> K路生成 -> 预筛 -> 判题 / 修复）")
        result = await pipeline.solve(p, language=target_lang)
    finally:
        elapsed = time.time() - t0
        await pipeline.client.close()
        pipeline.executor.close()

    _hr("③ 判题结果")
    verdict = "通过（全部测试点 AC）" if result["passed"] else f"未通过（{result.get('rounds', 0)} 轮修复后仍失败）"
    print(f"结论    ：{verdict}")
    print(f"修复轮数：{result.get('rounds')}")
    print(f"耗时    ：{elapsed:.1f}s")
    print(f"语言    ：{result.get('language_used')}")
    if result.get("language_advice"):
        print(f"语言建议：{result['language_advice']}")
    print(f"\n最终代码（{len(result['code'])} 字符）：\n")
    print(result["code"][:1500] + ("\n…（省略，完整见输出文件）" if len(result["code"]) > 1500 else ""))

    # 轨迹中的阶段摘要
    tf = Path(result.get("trace_file", ""))
    plan = None
    if tf.exists():
        _hr("④ 执行轨迹摘要")
        for line in tf.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            s = e.get("state")
            if s == "PLAN_DIVERSE":
                print(f"  多算法范式 Plan：{e.get('n')} 个 {e.get('tags')}")
            elif s == "GENERATED":
                print(f"  K 路生成：{e.get('k')} 个候选（{e.get('n_plans')} 个 plan，主 plan {e.get('k_main')} 路）")
            elif s == "TEST_GEN":
                print(f"  AI 边界用例：{e.get('n')} 个，暴力 oracle：{'有' if e.get('brute') else '无'}")
            elif s == "LOCAL_TESTED":
                print(f"  预筛：{e.get('prescreen_tests')} 个测试点，最优通过 {e.get('prescreen_pass')} 个")
            elif s == "JUDGED":
                vs = e.get("verdicts") or []
                ac = sum(1 for v in vs if v == "AC")
                print(f"  判题 round={e.get('round')} cand={e.get('cand')}：AC {ac}/{len(vs)}")
            elif s == "REFINED":
                print(f"  重规划（保留最优 {e.get('kept_best_pass')} 通过点）：{str(e.get('new_tags'))[:60]}")
            elif s == "CPP_FALLBACK":
                print(f"  C++17 兜底：{e.get('k')} 个候选")
            elif s in ("PLAN", "PLANNED") and "plan" in e and plan is None:
                plan = Plan(**e["plan"])

    if plan:
        _hr("⑤ 最终解题计划")
        print(f"算法标签：{plan.algorithm_tags}")
        print(f"声称复杂度：{plan.time_complexity}")
        for i, step in enumerate(plan.approach[:8], 1):
            print(f"  {i}. {step}")

    # 过程评估
    review = None
    if not args.no_review:
        _hr("⑥ 过程评估（五段式审查 + 蒙对检测）")
        from hy3_oj.agents import reviewer
        from hy3_oj.llm.client import Hy3Client
        from hy3_oj.sandbox.docker_executor import DockerExecutor

        client = Hy3Client(cfg)
        ex = DockerExecutor(cfg)
        try:
            review = await reviewer.review(
                client, p, plan, Solution(code=result["code"]),
                verdict, executor=ex, answer_passed=bool(result["passed"]),
            )
            print(f"过程评分：{review.process_score:.2f}")
            for sv in review.step_verdicts:
                mark = "PASS" if sv.passed else "FAIL"
                print(f"  [{mark}] {sv.step.value}" + (f" — {sv.evidence[:60]}" if sv.evidence else ""))
            if review.error_step:
                print(f"首个出错步骤：{review.error_step.value}（类型：{review.error_type.value if review.error_type else '—'}）")
            if review.lucky_pass_flags:
                print(f"[!] 蒙对标记：{review.lucky_pass_flags}")
        finally:
            ex.close()
            await client.close()

    # 题解
    explanation = ""
    if not args.no_explain:
        _hr("⑦ 文字题解（面向初学者）")
        from hy3_oj.agents import explainer
        from hy3_oj.llm.client import Hy3Client

        client = Hy3Client(cfg)
        try:
            explanation = await explainer.explain(
                client, p, Solution(code=result["code"]), plan=plan, review=review,
                judge_summary=verdict,
            )
            print(explanation[:1200] + ("\n…（省略，完整见输出文件）" if len(explanation) > 1200 else ""))
        finally:
            await client.close()

    # 输出文件
    out = args.out or f"runs/demo/{p.id.replace(':', '_')}.md"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    md = [
        f"# 单题演示：{p.id}", "",
        f"> 难度：{p.difficulty} ｜ 判题：{verdict} ｜ 语言：{result.get('language_used')}"
        f" ｜ 修复轮数：{result.get('rounds')} ｜ 耗时：{elapsed:.1f}s",
        "",
    ]
    if result.get("language_advice"):
        md += [f"> 语言建议：{result['language_advice']}", ""]
    md += ["## 最终代码", "", f"```python", result["code"], "```", "",
    ]
    if review is not None:
        md += [
            "## 过程评估", "",
            f"- 过程评分：{review.process_score:.2f}",
            f"- 首个出错步骤：{review.error_step.value if review.error_step else '无'}",
            f"- 错误类型：{review.error_type.value if review.error_type else '无'}",
            f"- 蒙对标记：{review.lucky_pass_flags or '无'}", "",
            "| 步骤 | 判定 | 证据 |", "|---|---|---|",
        ]
        md += [f"| {sv.step.value} | {'PASS' if sv.passed else 'FAIL'} | {sv.evidence[:80]} |" for sv in review.step_verdicts]
        md.append("")
    if explanation:
        md += ["## 文字题解", "", explanation]
    Path(out).write_text("\n".join(md), encoding="utf-8")
    _hr("输出")
    print(f"报告已写入：{out}")


if __name__ == "__main__":
    asyncio.run(main())
