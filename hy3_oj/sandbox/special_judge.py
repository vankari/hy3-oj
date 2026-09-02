"""多解特判（special judge）：为"答案不唯一"的题目生成并验证自定义校验器。

动机（618_B 根因）：重建类题目（"print any of them"）有多个合法输出，
精确比对会把合法解误判 WA——闭环连修 4 轮全灭实为判题口径问题，非模型能力。

流程：
1. needs_special_judge：题面含多解提示语时启用；
2. generate_checker：LLM 写 check(input_str, output_str) -> bool；
3. validate_checker：官方参考解的输出必须全部被 checker 接受（正例），
   空输出必须被拒绝（ sanity 反例）；全部通过才可信，否则回退精确比对；
4. checker 按题缓存 runs/checkers/，判题时在容器内与被测代码同沙箱执行。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from hy3_oj.core.schemas import GenMode, Problem, Solution
from hy3_oj.llm.client import Hy3Client
from hy3_oj.sandbox.docker_executor import DockerExecutor

log = logging.getLogger(__name__)

_CACHE_DIR = Path("runs/checkers")

# 多解题面提示语（中英；命中即启用特判）
_MULTI_ANSWER_RE = re.compile(
    r"(print any|any valid|any of them|multiple (possible )?solutions|"
    r"any of the possible|if there are (several|multiple)|任一|任意(一个|可行)|多种合法)",
    re.IGNORECASE,
)

_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def needs_special_judge(problem: Problem) -> bool:
    """题面提示答案不唯一时需要特判。"""
    return bool(_MULTI_ANSWER_RE.search(problem.statement))


def _cache_path(problem_id: str) -> Path:
    safe = re.sub(r"[^\w\-.]+", "_", problem_id)
    return _CACHE_DIR / f"{safe}.py"


def _extract_code(text: str) -> str:
    m = _CODE_RE.search(text)
    code = m.group(1) if m else text
    return code if "def check(" in code else ""


async def generate_checker(client: Hy3Client, problem: Problem) -> str | None:
    """LLM 快思考编写校验函数（结构化代码输出必须快思考，慢思考会截断）。"""
    user = (
        "以下竞赛题目的正确答案不唯一（special judge 场景）。"
        "请编写 Python 校验函数 check(input_str: str, output_str: str) -> bool："
        "接收测试输入与被测程序的标准输出，当且仅当输出对该输入是**任意一个合法答案**时返回 True。\n"
        "要求：只用标准库、自包含；解析失败/格式错误返回 False；"
        "**解析必须宽容**：用 split() 按空白分词读取数字/token，不要假设严格的行结构"
        "（测试数据可能有多余空行、行尾空格或不同的换行风格）；"
        "输出 token 级空白差异应宽容，但答案语义必须严格按题意验证"
        "（如重建排列题：验证输出是 1..n 的排列且与输入矩阵完全一致）。\n"
        "只输出代码（check 函数与必要辅助函数），不要解释。\n\n"
        f"题目：\n{problem.statement[:5000]}"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是判题器工程师，只输出 Python 代码。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.0, max_tokens=4096, stage="checker_gen",
        )
        code = _extract_code(r.content)
    except Exception as e:  # noqa: BLE001
        log.warning("checker 生成失败 %s: %s", problem.id, e)
        return None
    return code or None


def validate_checker(
    executor: DockerExecutor, problem: Problem, checker_code: str
) -> tuple[bool, str]:
    """用官方参考解的输出反向验证 checker。

    返回 (是否可信, 失败详情)。可信 = 参考解输出全部接受 + 空输出拒绝。
    """
    tests = (problem.samples + problem.public_tests + problem.private_tests)[:5]
    if not tests or not problem.reference_solutions:
        return False, "无测试点或无参考解"
    ref_outs = executor.run_stdout(Solution(code=problem.reference_solutions[0]), [t.input for t in tests])
    if ref_outs is None:
        return False, "参考解执行失败"
    pairs = [(t.input, o) for t, o in zip(tests, ref_outs)]
    pairs.append((tests[0].input, ""))  # 反例：空输出必须拒绝（防空泛恒真 checker）
    verdicts = executor.run_checker(checker_code, pairs)
    if verdicts is None or len(verdicts) != len(pairs):
        return False, "checker 容器内执行崩溃"
    for (inp, out), v in zip(pairs[:-1], verdicts[:-1]):
        if v is not True:
            return False, (
                f"参考解合法输出被拒绝：input={inp[:120]!r} ref_output={out[:120]!r} verdict={v}"
            )
    if verdicts[-1] is not False:
        return False, f"空输出未被拒绝（恒真 checker）：verdict={verdicts[-1]}"
    return True, ""


async def repair_checker(
    client: Hy3Client, problem: Problem, checker_code: str, failure: str
) -> str | None:
    """验证失败后让 LLM 修一次 checker（给出失败详情）。"""
    user = (
        "以下 special judge 校验函数在反向验证中失败（官方参考解的合法输出被它拒绝，"
        "或空输出被它接受）。请修正后只输出完整代码。\n\n"
        f"失败详情：{failure}\n\n"
        "要求：只用标准库；解析宽容（split() 分词，不假设严格行结构）；"
        "语义严格按题意。\n\n"
        f"题目：\n{problem.statement[:3000]}\n\n"
        f"待修正的代码：\n```python\n{checker_code}\n```"
    )
    try:
        r = await client.chat(
            [{"role": "system", "content": "你是判题器工程师，只输出 Python 代码。"},
             {"role": "user", "content": user}],
            mode=GenMode.FAST, temperature=0.0, max_tokens=4096, stage="checker_repair",
        )
        code = _extract_code(r.content)
    except Exception as e:  # noqa: BLE001
        log.warning("checker 修复失败 %s: %s", problem.id, e)
        return None
    return code or None


async def get_checker(
    client: Hy3Client, executor: DockerExecutor, problem: Problem, use_cache: bool = True
) -> str | None:
    """主入口：生成 → 验证 →（失败则修一次再验证）→ 缓存；不可信返回 None。"""
    if use_cache and _cache_path(problem.id).exists():
        return _cache_path(problem.id).read_text(encoding="utf-8")
    import asyncio

    code = await generate_checker(client, problem)
    if not code:
        return None
    ok, detail = await asyncio.to_thread(validate_checker, executor, problem, code)
    if not ok:
        repaired = await repair_checker(client, problem, code, detail)
        if repaired:
            code = repaired
            ok, detail = await asyncio.to_thread(validate_checker, executor, problem, code)
    if not ok:
        log.info("checker 未通过反向验证，回退精确比对: %s (%s)", problem.id, detail)
        return None
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(problem.id).write_text(code, encoding="utf-8")
    return code
