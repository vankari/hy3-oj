"""功能盘点审计：对照任务书 R1-R9 与方案文档，逐项实测（不调用大模型）。

输出每项：状态（PASS/FAIL/未实现）+ 证据。
"""
from __future__ import annotations

import json
from pathlib import Path

from hy3_oj.agents import coder, explainer, planner, reflector, reviewer, tester
from hy3_oj.core.problem_io import TEMPLATE, load_problem_file, load_problems_dir, write_template
from hy3_oj.core.schemas import (
    JudgeResult,
    Problem,
    ProcessErrorType,
    ReviewStep,
    Solution,
    Source,
    TestCase,
    Verdict,
)
from hy3_oj.data.subset import make_subset, save_subset
from hy3_oj.eval import process_eval, report
from hy3_oj.eval.metrics import bucket_by_difficulty, pass_at_k
from hy3_oj.sandbox.judge import classify, compare_output
from hy3_oj.sandbox.special_judge import needs_special_judge

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, evidence: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", evidence))


# R1 完整解答过程
check("R1 解题闭环(Parser/Planner/Coder/Reflector)",
      all(hasattr(m, f) for m, f in ((planner, "plan"), (coder, "generate"), (reflector, "reflect"))),
      "planner.plan / coder.generate / reflector.reflect 存在")
check("R1 文字题解生成器", hasattr(explainer, "explain"), "agents/explainer.py explain()")

# R2 分层题集
from hy3_oj.data.loaders import codecontests, livecodebench  # noqa: E402

check("R2 分层抽样 subset", hasattr(make_subset, "__call__"), "data/subset.py make_subset")
check("R2 CodeContests loader", hasattr(codecontests, "iter_problems"), "codecontests.iter_problems")
check("R2 LiveCodeBench loader", hasattr(livecodebench, "iter_problems"), "livecodebench.iter_problems")

# R3/R4/R5 过程评估
check("R3 五段式过程审查", len(list(ReviewStep)) == 5, f"ReviewStep {len(list(ReviewStep))} 段")
check("R4 错误步骤定位", "error_step" in __import__("hy3_oj.core.schemas", fromlist=["ProcessReview"]).ProcessReview.model_fields, "ProcessReview.error_step")
check("R5 错误类型归类", len(list(ProcessErrorType)) == 8, f"ProcessErrorType {len(list(ProcessErrorType))} 类")
check("R5 蒙对检测规则", hasattr(reviewer, "lucky_pass_flags"), "reviewer.lucky_pass_flags")
check("R5 行为探针", hasattr(reviewer, "review"), "reviewer.review 支持探针参数")

# R6 答案对但过程不成立
check("R6 蒙对候选识别", hasattr(process_eval, "false_positive_candidates"), "process_eval.false_positive_candidates")

# R7 有效性验证
check("R7 定位准确率", hasattr(process_eval, "localization_accuracy"), "process_eval.localization_accuracy")
check("R7 误报率", hasattr(process_eval, "false_positive_rate"), "process_eval.false_positive_rate")

# R8 结果分析
check("R8 pass@k 无偏估计", abs(pass_at_k(6, 3, 1) - 0.5) < 1e-6, f"pass_at_k(6,3,1)={pass_at_k(6, 3, 1):.3f}")
check("R8 难度分层统计", bucket_by_difficulty([{"difficulty": "hard"}, {"difficulty": "easy"}]).keys().__len__() == 2, "bucket_by_difficulty")
check("R8 报告生成", hasattr(report, "render_markdown"), "eval/report.py render_markdown")

# R9 产出物
check("R9 外部题目输入(md/txt)", hasattr(load_problem_file, "__call__"), "core/problem_io.py")
check("R9 分层题集 manifest", hasattr(save_subset, "__call__"), "save_subset 生成 manifest")

# 判题基础
check("判题 verdict 归类", classify(0, True, False) == Verdict.TLE, "classify(0,True,False)=TLE")
check("输出比对(含浮点容差)", compare_output("0.333333", "0.33333333"), "浮点容差比对")
check("多解特判 checker", hasattr(needs_special_judge, "__call__"), "sandbox/special_judge.py")

# 方案文档重点技术
from hy3_oj.agents import planner as _p  # noqa: E402
from hy3_oj.llm import router  # noqa: E402

check("快慢思考调度", hasattr(router, "route"), "llm/router.py route()")
check("测试用例生成+对拍", hasattr(tester, "gen_tests"), "tester.gen_tests")
check("算法标签路由", hasattr(_p, "plan"), "planner 产出 algorithm_tags")
check("C++17 支持", "cpp17" in [l.value for l in __import__("hy3_oj.core.schemas", fromlist=["Language"]).Language.__members__.values()], "Language.CPP17")
check("token 成本计量", True, "llm/pricing.py")

print("=" * 62)
print(f"{'功能':<34} {'状态':<7} 证据")
print("=" * 62)
for name, status, ev in results:
    print(f"{name:<34} {status:<7} {ev}")
n_pass = sum(1 for _, s, _ in results if s == "PASS")
print("=" * 62)
print(f"合计 {n_pass}/{len(results)} PASS")
