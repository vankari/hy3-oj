"""Coder：K 路温度分层采样生成代码（AlphaCodium 两阶段：先要点复述再写码）。"""
from __future__ import annotations

import re

from hy3_oj.core.schemas import GenMode, Language, Plan, Problem, Solution
from hy3_oj.llm.client import Hy3Client

_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_CPP_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c\+\+17|C\+\+)?\s*\n(.*?)```", re.DOTALL)

# call-based 判题约定的题面标记（与 livecodebench loader 的 _CALL_BASED_NOTICE 对齐）
_CALL_MARK = "**判题约定（call-based）**"
_FUNC_NAME_RE = re.compile(r"Solution\(\)\.(\w+)\(")
_MAIN_BLOCK_RE = re.compile(r"\n*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:.*$", re.DOTALL)


def _strip_main_block(code: str) -> str:
    """剥离代码末尾的 __main__ 驱动块（保留其余实现）。"""
    return _MAIN_BLOCK_RE.sub("\n", code).rstrip() + "\n"


def ensure_driver(code: str, problem: Problem) -> str:
    """call-based 题补挂判题驱动（模型漏写驱动入口时不会全 RE）。

    模型常只输出 Solution 类而漏掉驱动入口；若代码已有 __main__ 驱动则不重复追加。
    """
    if not is_call_based(problem):
        return code
    m = _FUNC_NAME_RE.search(problem.statement)
    if not m:
        return code
    func_name = m.group(1)

    # 强制剥离模型自带的 __main__ 驱动块（它会复制题面/记忆中的旧整体解析写法 → 参数展开错误），
    # 再注入我们唯一可信的逐行解析驱动（leetcode:3532/3677 根因）。
    code = _strip_main_block(code)
    # 关键：LCB 官方 testcase 每参数占一行（如 "[[0,1,-1],[1,-2,3],[2,-3,4]]" 是一个二维数组参数）。
    # 若整体 json.loads 后展开，会把单行的嵌套数组当成参数列表 → TypeError（leetcode:3677 实测）。
    driver = (
        "\n\nif __name__ == \"__main__\":\n"
        "    import json, sys\n"
        "    _data = sys.stdin.read()\n"
        "    _lines = [l for l in _data.splitlines() if l.strip()]\n"
        "    try:\n"
        "        args = [json.loads(l) for l in _lines]\n"
        "    except Exception:\n"
        "        args = [json.loads(_data)]  # 兜底：整体作为一个参数（不展开，避免参数个数误判）\n"
        f"    print(json.dumps(Solution().{func_name}(*args)))\n"
    )
    return code + driver


def extract_code(text: str, language: Language = Language.PYTHON3) -> str:
    """从模型输出提取代码块；无代码块时回退为全文（尽力而为）。

    C++ 需先试 ```cpp，找不到再退 python 正则（模型偶发标错语言）。
    """
    if language == Language.CPP17:
        m = _CPP_CODE_RE.search(text)
        if m and "#include" in m.group(1):
            return m.group(1).strip()
    m = _CODE_RE.search(text)
    return (m.group(1) if m else text).strip()


def is_call_based(problem: Problem) -> bool:
    """题面含 call-based 判题约定（LeetCode 风格：实现类方法，非 stdin 解析）。"""
    return _CALL_MARK in problem.statement and _FUNC_NAME_RE.search(problem.statement) is not None


def build_messages(problem: Problem, plan: Plan | None = None, language: Language = Language.PYTHON3) -> list[dict[str, str]]:
    """组装 Coder 提示（要点化 plan 可选；基线直出时 plan=None）。

    关键：判题协议自适应。call-based 题（LeetCode）禁止提示"stdin 读入"——
    否则模型会写 input() 解析，遇到 JSON 参数字面量直接 RE（leetcode:3265/3779 根因）。
    C++17 用于 hard 档 TLE 攻坚（Python 性能不足）。
    """
    want_cpp = language == Language.CPP17
    samples = "\n".join(
        f"输入：\n{t.input}\n输出：\n{t.expected_output or ''}" for t in problem.samples[:2]
    )
    plan_text = ""
    if plan and plan.approach:
        plan_text = "解题计划：\n" + "\n".join(f"- {s}" for s in plan.approach) + "\n\n"

    if is_call_based(problem):
        io_rule = (
            "**严格遵守题面中的「判题约定（call-based）」**：实现题面指定的类与方法签名，"
            "不要写 input() 逐行解析，不要自己实现驱动入口（驱动由判题器附加）。"
            "开头写 `from typing import *`。"
        )
    elif want_cpp:
        io_rule = "标准输入读入、标准输出写出（stdin/stdout 约定）；用 cin/cout 并关闭同步。"
    else:
        io_rule = "标准输入读入、标准输出写出（stdin/stdout 约定）。"

    lang_name, fence = ("C++17", "```cpp") if want_cpp else ("Python3", "```python")
    stdlib = "仅标准库（bits/stdc++.h）" if want_cpp else "仅标准库"
    user = (
        f"{plan_text}题目：\n{problem.statement}\n\n样例：\n{samples}\n\n"
        f"先复述要点化解法（不超过 5 条），然后输出完整 {lang_name} 代码"
        f"（{fence} 代码块，{stdlib}；{io_rule}）。"
    )
    return [
        {"role": "system", "content": "你是竞赛选手。严格按约束实现，不输出调试信息。"},
        {"role": "user", "content": user},
    ]


async def generate(
    client: Hy3Client,
    problem: Problem,
    plan: Plan | None = None,
    k: int = 1,
    temperatures: list[float] | None = None,
    mode: GenMode = GenMode.FAST,
    language: Language = Language.PYTHON3,
) -> list[Solution]:
    """K 路采样：逐路调用（缓存使重复调用零成本），提取代码块为 Solution。"""
    temps = (temperatures or [0.2])[:k] or [0.2]
    messages = build_messages(problem, plan, language=language)
    solutions: list[Solution] = []
    for i in range(k):
        r = await client.chat(messages, mode=mode, temperature=temps[i % len(temps)], stage="code")
        code = extract_code(r.content, language=language)
        if language == Language.PYTHON3:
            code = ensure_driver(code, problem)  # call-based 题补挂驱动，避免漏写 → 全 RE
        solutions.append(
            Solution(code=code, plan_ref="inline" if plan else None, language=language,
                     temperature=temps[i % len(temps)], gen_mode=mode)
        )
    return solutions
