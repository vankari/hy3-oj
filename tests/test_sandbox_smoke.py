"""沙箱冒烟测试：Docker 可用性 + judge 纯逻辑（Docker 未启动时自动 skip）。"""
from __future__ import annotations

import pytest

from hy3_oj.core.schemas import Verdict
from hy3_oj.sandbox.judge import classify, compare_output


def test_compare_output_exact_and_trim() -> None:
    assert compare_output("6\n", "6")
    assert compare_output("1 2 3", "1 2 3\n")


def test_compare_output_float_tolerance() -> None:
    assert compare_output("0.333333", "0.3333333333")
    assert not compare_output("0.5", "0.6")


def test_compare_output_token_mismatch() -> None:
    assert not compare_output("1 2", "1 2 3")


def test_classify() -> None:
    assert classify(exit_code=0, timed_out=False, compile_failed=True) == Verdict.CE
    assert classify(exit_code=0, timed_out=True, compile_failed=False) == Verdict.TLE
    assert classify(exit_code=1, timed_out=False, compile_failed=False) == Verdict.RE
    assert classify(exit_code=0, timed_out=False, compile_failed=False) == Verdict.AC


def test_docker_available() -> None:
    """Docker Desktop 启动后此用例应通过；未启动则 skip（不阻塞 CI）。"""
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception:
        pytest.skip("Docker Desktop 未启动，跳过容器冒烟（D4 前请启动）")
