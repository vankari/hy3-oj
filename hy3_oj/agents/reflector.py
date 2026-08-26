"""Reflector：CE/RE/WA/TLE 归因与定向修复指令（骨架）。

输入 JudgeResult + 轨迹 → 输出 Reflection。慢思考；按 verdict 分流：
CE→编译错误定位；RE→栈信息归因；WA→先构造反例再修复；TLE→复杂度重分析、换更优算法。
TODO(D7): 实现 reflect(result, trace) -> Reflection；prompts/repair/*.yaml 四模板。
"""
from __future__ import annotations
