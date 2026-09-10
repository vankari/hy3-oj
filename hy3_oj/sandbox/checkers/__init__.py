"""人工维护的确定性校验器，禁止从题目中执行任意宿主机代码。"""
from pathlib import Path


def checker_source(name: str) -> str:
    if name != "integer_decomposition":
        raise ValueError(f"Unknown checker: {name}")
    return Path(__file__).with_name("integer_decomposition.py").read_text(encoding="utf-8")
