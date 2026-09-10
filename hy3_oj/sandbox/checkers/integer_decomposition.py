"""N=ab+c 的最小和校验器。参数化思想来自苏剑林博客 archives/9775。

实现使用整数平方根与当前可行解上界，避免浮点边界误差；兼作生成标准答案的 oracle。
"""
from math import isqrt
import re


def optimal(n: int) -> tuple[int, int, int]:
    if n <= 0:
        return 0, 0, n
    root = isqrt(n)
    if root * root == n:
        return root, root, 0
    p0 = isqrt(4 * n)

    def at_sum(p):
        delta = p * p - 4 * n
        q = isqrt(max(0, delta))
        if q * q < delta:
            q += 1
        q += (p - q) & 1
        a, b = (p - q) // 2, (p + q) // 2
        return a, b, n - a * b

    best = min((at_sum(p0), at_sum(p0 + 1)), key=sum)
    best_sum = sum(best)
    p = p0 + 1
    while p < best_sum:
        candidate = at_sum(p)
        score = sum(candidate)
        if score < best_sum:
            best, best_sum = candidate, score
        p += 1
    return best


def check(input_str: str, output_str: str) -> bool:
    try:
        inputs = input_str.split()
        values = output_str.split()
        if len(inputs) != 1 or len(values) != 3:
            return False
        # 只接受十进制整数，拒绝浮点、科学计数法和额外解释。
        if any(re.fullmatch(r"[+-]?[0-9]+", v) is None for v in values):
            return False
        n = int(inputs[0])
        a, b, c = map(int, values)
        return n > 100 and min(a, b, c) >= 0 and a * b + c == n and a + b + c == sum(optimal(n))
    except (ValueError, OverflowError):
        return False
