"""过程评估器有效性验证（任务书 R7）。

- 定位准确率：官方参考解 + 规则自动注入已知 bug（注入步骤为 ground truth），
  Reviewer 预测 error_step 与注入步骤比对，段级命中率目标 ≥70%。
- 误报率：官方正确参考解上跑 Reviewer，被判过程有问题的样本人工抽检，
  区分真实问题 vs 误报，目标 ≤20%；抽检记录落盘（题号/判定/理由/抽检人）。
"""
from __future__ import annotations

import random
import re

from hy3_oj.core.schemas import ProcessReview, ReviewStep

# ---------- bug 注入（规则驱动，注入位置 = ground truth） ----------

def inject_bug(code: str, rng: random.Random) -> tuple[str, ReviewStep, str] | None:
    """向正确解注入一个已知 bug。

    返回 (注入后代码, 注入步骤 ground truth, 描述)；无法注入返回 None。
    每种注入都标注其"过程层面"对应出错的步骤段。
    """
    strategies = []

    # ①边界处理：off-by-one（range(n) → range(n-1)，或 <= 改 <）
    if re.search(r"range\(\s*\w+\s*\)", code):
        strategies.append(("edge_off_by_one", ReviewStep.EDGE_HANDLING,
                           lambda c: re.sub(r"range\(\s*(\w+)\s*\)", r"range(\1-1)", c, count=1),
                           "range(n) 改为 range(n-1)，漏掉最后一个元素"))
    if " <= " in code:
        strategies.append(("edge_le_to_lt", ReviewStep.EDGE_HANDLING,
                           lambda c: c.replace(" <= ", " < ", 1),
                           "<= 改为 <，边界取等错误"))

    # ⑤实现一致性：变量 swap / 运算符翻转（+ 改 -，* 改 +）
    if " + " in code:
        strategies.append(("impl_plus_to_minus", ReviewStep.IMPL_CONSISTENCY,
                           lambda c: c.replace(" + ", " - ", 1),
                           "+ 改为 -，实现逻辑错误"))

    # ②算法选型：max 改 min（方向性错误，属算法逻辑而非单纯笔误）
    if "max(" in code:
        strategies.append(("algo_max_to_min", ReviewStep.ALGO_SELECTION,
                           lambda c: c.replace("max(", "min(", 1),
                           "max 改为 min，求解方向错误"))

    if not strategies:
        return None
    name, step, fn, desc = rng.choice(strategies)
    try:
        buggy = fn(code)
    except Exception:  # noqa: BLE001
        return None
    if buggy == code:
        return None
    return buggy, step, f"{name}: {desc}"


# ---------- 定位准确率 ----------

def localization_accuracy(reviews: list[tuple[ProcessReview, ReviewStep]]) -> dict:
    """reviews: (Reviewer 评估结果, 注入步骤 ground truth)。段级命中统计。"""
    n = len(reviews)
    if not n:
        return {"n": 0, "hit": 0, "accuracy": 0.0}
    hit = sum(1 for review, gt in reviews if review.error_step == gt)
    detected = sum(1 for review, _ in reviews if review.error_step is not None)
    return {
        "n": n,
        "hit": hit,
        "detected": detected,
        "accuracy": hit / n,
        "detection_rate": detected / n,
        "target": 0.70,
        "pass": (hit / n) >= 0.70,
    }


# ---------- 误报率（需人工抽检） ----------

def false_positive_candidates(reviews: list[tuple[str, ProcessReview]]) -> list[dict]:
    """蒙对定罪候选（供人工抽检）：仅收集 lucky_pass_flags 非空的 AC 样本。

    定罪口径（v0.5 起，由 mid100 抽检数据驱动）：只有机器验证的证据才定罪——
    行为探针（题面官方样例 + 参考解反向校验）或"规则+LLM 双确认"的信号。
    LLM 逐步判定/打分层在 AC 解上误报率高（13/14），只作 R8"过程存疑"分析维度，
    不作 R6 蒙对定罪依据。
    """
    flagged = []
    for pid, review in reviews:
        if review.lucky_pass_flags:
            flagged.append({
                "problem_id": pid,
                "error_step": review.error_step.value if review.error_step else None,
                "error_type": review.error_type.value if review.error_type else None,
                "lucky_pass_flags": review.lucky_pass_flags,
                "process_score": review.process_score,
                "human_verdict": None,  # 人工填: "real" / "false_positive"
                "human_note": "",
            })
    return flagged


def process_suspects(reviews: list[tuple[str, ProcessReview]]) -> list[dict]:
    """过程存疑清单（R8 分析维度，非蒙对定罪）：LLM 判过程不成立但无定罪证据。"""
    suspects = []
    for pid, review in reviews:
        if review.lucky_pass_flags:
            continue
        if review.error_step is not None or review.process_score < 0.8:
            suspects.append({
                "problem_id": pid,
                "error_step": review.error_step.value if review.error_step else None,
                "error_type": review.error_type.value if review.error_type else None,
                "process_score": review.process_score,
            })
    return suspects


def false_positive_rate(spot_checks: list[dict]) -> dict:
    """根据人工抽检记录算误报率（目标 ≤20%）。"""
    checked = [s for s in spot_checks if s.get("human_verdict") in ("real", "false_positive")]
    n = len(checked)
    if not n:
        return {"n_flagged": len(spot_checks), "n_checked": 0, "fp_rate": None}
    fp = sum(1 for s in checked if s["human_verdict"] == "false_positive")
    return {
        "n_flagged": len(spot_checks),
        "n_checked": n,
        "false_positives": fp,
        "fp_rate": fp / n,
        "target": 0.20,
        "pass": (fp / n) <= 0.20,
    }
