"""verdict 解析与输出比对（骨架）。

逐测试点比对：trim 后精确比较 + 浮点容差档；
exit code/超时/编译失败 → CE/RE/TLE 分类；返回首个失败点摘要。
TODO(D4): 实现 compare_output 与 classify（与 CodeContests verdict 对拍校准，目标一致率≥99%）。
"""
from __future__ import annotations

from hy3_oj.core.schemas import Verdict

FLOAT_TOL = 1e-6


def compare_output(expected: str | None, actual: str | None, float_tol: float = FLOAT_TOL) -> bool:
    """输出比对：trim 后精确比较；失败则按浮点容差逐 token 重比。

    None 表示"执行失败/无输出"（如超时、进程被杀），一律判为不一致而非崩溃——
    生产环境里暴力解对拍时 run_stdout 可能返回 None（tester.gen_brute_force 踩过）。
    """
    if expected is None or actual is None:
        return False
    if expected.strip() == actual.strip():
        return True
    exp_toks, act_toks = expected.split(), actual.split()
    if len(exp_toks) != len(act_toks):
        return False
    for e, a in zip(exp_toks, act_toks):
        if e == a:
            continue
        try:
            if abs(float(e) - float(a)) > float_tol:
                return False
        except ValueError:
            return False
    return True


def classify(exit_code: int, timed_out: bool, compile_failed: bool) -> Verdict:
    """按执行信号归类结果层 verdict。"""
    if compile_failed:
        return Verdict.CE
    if timed_out:
        return Verdict.TLE
    if exit_code != 0:
        return Verdict.RE
    return Verdict.AC
