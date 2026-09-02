"""call-based 驱动逐行解析单测（leetcode:3677 根因回归测试）。

根因：LCB testcase 每个参数占一行。整体 json.loads 后展开会把单行嵌套数组
（如 [[0,1,-1],[1,-2,3],[2,-3,4]]，本是一个二维数组参数）当成参数列表展开，
导致 TypeError: takes 2 positional arguments but 4 were given。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from hy3_oj.agents.coder import ensure_driver, is_call_based
from hy3_oj.core.schemas import Problem, Source

STATEMENT = (
    "---\n**判题约定（call-based）**：\n"
    "```python\nclass Solution:\n    def maximumAmount(self, coins) -> int: ...\n```\n"
    "```python\nif __name__ == \"__main__\":\n    import json, sys\n"
    "    args = json.loads(sys.stdin.read())\n    print(json.dumps(Solution().maximumAmount(*args)))\n```\n"
)


def problem() -> Problem:
    return Problem(id="leetcode:3677", source=Source.LIVECODEBENCH, statement=STATEMENT)


CLASS_ONLY = "from typing import *\nclass Solution:\n    def maximumAmount(self, coins):\n        return len(coins)\n"


def run_code(code: str, stdin_data: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.py"
        p.write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, str(p)], input=stdin_data,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()


def test_driver_single_nested_array_not_expanded() -> None:
    """单行嵌套数组 = 一个参数（回归 3677 根因）。"""
    code = ensure_driver(CLASS_ONLY, problem())
    assert args_count(code) == 1
    out = run_code(code, "[[0, 1, -1], [1, -2, 3], [2, -3, 4]]\n")
    assert out == "3"  # len(coins) = 3 行


def test_driver_two_lines_two_args() -> None:
    """两行 = 两个参数（leetcode:3265 场景）。"""
    code = ensure_driver(
        "from typing import *\nclass Solution:\n    def countPairs(self, nums, k):\n        return len(nums) + k\n",
        problem(),
    )
    # 函数名来自 statement（maximumAmount），这里仅验证逐行解析：改用同签名方法
    code = code.replace("maximumAmount", "countPairs")
    out = run_code(code, "[1, 2, 3, 4, 5, 6]\n1\n")
    assert out == "7"  # 6 + 1


def test_driver_fallback_whole_json() -> None:
    """跨行 JSON（逐行解析失败）时兜底整体解析为单个参数（不展开）。"""
    code = ensure_driver(CLASS_ONLY, problem())
    out = run_code(code, "[[0, 1],\n [2, 3]]\n")
    assert out == "2"  # 整体作为一个二维数组参数 → len(coins) = 2


def args_count(code: str) -> int:
    """在受控环境下数驱动实际传给方法的参数个数。"""
    probe = code.replace(
        "print(json.dumps(Solution().maximumAmount(*args)))",
        "print(len(args))",
    )
    return int(run_code(probe, "[[0, 1, -1], [1, -2, 3], [2, -3, 4]]\n"))


def test_is_call_based_still_detects() -> None:
    assert is_call_based(problem())


def test_strips_stale_main_block() -> None:
    """模型复制的旧整体解析驱动必须被剥离并替换（leetcode:3532 根因）。

    旧驱动 `args = json.loads(sys.stdin.read())` 会把单行二维数组展开成多个参数，
    报 TypeError: takes 2 positional arguments but 3 were given。
    """
    stale = (
        "from typing import *\nclass Solution:\n    def maximumAmount(self, coins):\n        return len(coins)\n\n"
        "if __name__ == \"__main__\":\n"
        "    import json, sys\n"
        "    args = json.loads(sys.stdin.read())\n"
        "    print(json.dumps(Solution().maximumAmount(*args)))\n"
    )
    out = ensure_driver(stale, problem())
    assert out.count("__main__") == 1  # 只保留我们注入的那一个
    assert "json.loads(sys.stdin.read())" not in out  # 旧整体解析已移除
    assert "_lines = [l for l in _data.splitlines()" in out
    probe = out.replace("print(json.dumps(Solution().maximumAmount(*args)))", "print(len(args))")
    assert run_code(probe, "[[0, 1], [0, 2]]\n") == "1"  # 单行二维数组 = 1 个参数
