"""Tester：边界测试用例生成 + 暴力对拍（骨架）。

输入 Problem(+Plan) → 输出 TestCase[] + brute-force 参考解；
用例先经 validator 自校验（满足输入约束）再入库（CodeContests+ 思路）；
对简单题生成暴力解做差分对拍，拦截无效提交。
TODO(D8): 实现 gen_tests(problem) 与 differential_check(solution, brute)。
"""
from __future__ import annotations
