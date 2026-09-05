"""DockerExecutor 真实容器冒烟（Docker 未启动时自动 skip）。

覆盖：AC / WA / RE / TLE 四类判题路径 + 网络隔离。
"""
from __future__ import annotations

import pytest

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Solution, TestCase, Verdict

docker = pytest.importorskip("docker")


@pytest.fixture(scope="module")
def executor():
    from hy3_oj.sandbox.docker_executor import DockerExecutor

    try:
        ex = DockerExecutor(load_config())
    except docker.errors.DockerException as e:
        # Docker 不可用时 skip 而非 error：区分"环境不满足"与"代码错误"
        pytest.skip(f"Docker 不可用（{type(e).__name__}）：请启动 Docker Desktop")
    try:
        if not ex.ping():
            pytest.skip("Docker Desktop 未启动")
        ex._client.images.get("python:3.11-slim")
    except docker.errors.DockerException as e:
        pytest.skip(f"Docker 守护进程异常（{type(e).__name__}）：请重启 Docker Desktop")
    except docker.errors.ImageNotFound:
        pytest.skip("镜像 python:3.11-slim 未拉取（docker pull python:3.11-slim）")
    yield ex
    ex.close()


TESTS = [TestCase(input="3\n1 2 3\n", expected_output="6\n"),
         TestCase(input="2\n10 20\n", expected_output="30\n")]


def test_ac(executor) -> None:
    code = "n=int(input()); a=list(map(int,input().split())); print(sum(a))"
    results = executor.execute(Solution(code=code), TESTS)
    assert all(r.verdict == Verdict.AC for r in results)


def test_wa(executor) -> None:
    code = "n=int(input()); a=list(map(int,input().split())); print(sum(a)+1)"
    results = executor.execute(Solution(code=code), TESTS)
    assert all(r.verdict == Verdict.WA for r in results)
    assert results[0].diff_excerpt


def test_re(executor) -> None:
    code = "print(1/0)"
    results = executor.execute(Solution(code=code), TESTS[:1])
    assert results[0].verdict == Verdict.RE
    assert "ZeroDivisionError" in results[0].stderr


def test_tle(executor) -> None:
    code = "while True: pass"
    results = executor.execute(Solution(code=code), TESTS[:1])
    assert results[0].verdict == Verdict.TLE


def test_network_disabled(executor) -> None:
    code = "import urllib.request; print(urllib.request.urlopen('http://example.com', timeout=3).status)"
    results = executor.execute(Solution(code=code), TESTS[:1])
    assert results[0].verdict == Verdict.RE  # 断网容器内联网必然报错
