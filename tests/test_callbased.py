"""call-based（LeetCode 风格）判题协议适配单测。

根因：Coder 提示词固定写"stdin 读入"，而 LCB 的 leetcode 题是 call-based
（实现类方法 + JSON 参数驱动），模型写 input() 解析 → 遇 JSON 字面量直接 RE
（leetcode:3265/3779 实测均为该问题）。
"""
from __future__ import annotations

from hy3_oj.agents.coder import build_messages, ensure_driver, is_call_based
from hy3_oj.core.schemas import Problem, Source

CALL_STATEMENT = (
    "Count the number of valid pairs.\n\n---\n"
    "**判题约定（call-based）**：本题不读 stdin 逐行输入。请实现以下类与方法签名：\n\n"
    "```python\nclass Solution:\n    def countPairs(self, nums: List[int], k: int) -> int: ...\n```\n\n"
    "```python\nif __name__ == \"__main__\":\n    import json, sys\n"
    "    args = json.loads(sys.stdin.read())\n    print(json.dumps(Solution().countPairs(*args)))\n```\n"
)


def call_problem() -> Problem:
    return Problem(id="leetcode:3265", source=Source.LIVECODEBENCH, statement=CALL_STATEMENT)


def stdin_problem() -> Problem:
    return Problem(id="cf-1", source=Source.CODECONTESTS, statement="Given n integers, output their sum.")


def test_detect_call_based() -> None:
    assert is_call_based(call_problem())
    assert not is_call_based(stdin_problem())


def test_build_messages_protocol() -> None:
    msgs = build_messages(call_problem())
    body = msgs[-1]["content"]
    assert "不要写 input() 逐行解析" in body
    assert "stdin 读入/stdout 输出" not in body

    stdin_body = build_messages(stdin_problem())[-1]["content"]
    assert "stdin/stdout 约定" in stdin_body


def test_ensure_driver_appended() -> None:
    cls_only = "class Solution:\n    def countPairs(self, nums, k):\n        return 1\n"
    out = ensure_driver(cls_only, call_problem())
    assert '__name__ == "__main__"' in out
    assert "Solution().countPairs(*args)" in out


def test_ensure_driver_replaces_own_main() -> None:
    """call-based 题：任何自带 __main__ 都被替换为唯一可信驱动（旧驱动会参数展开错误）。

    重复调用结果稳定（第二次注入与第一次一致），保证幂等收敛。
    """
    with_driver = "class Solution:\n    def f(self): return 1\n\nif __name__ == '__main__':\n    pass\n"
    out1 = ensure_driver(with_driver, call_problem())
    out2 = ensure_driver(out1, call_problem())
    assert out2 == out1  # 幂等收敛
    assert out1.count("__main__") == 1


def test_ensure_driver_skips_stdin_problems() -> None:
    code = "n = int(input())\nprint(n)"
    assert ensure_driver(code, stdin_problem()) == code
