"""C++17 沙箱冒烟（Docker 未启动/镜像缺失时自动 skip）。

覆盖：AC / WA / CE（编译失败）/ TLE / RE。
"""
from __future__ import annotations

import pytest

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Language, Solution, Verdict

docker = pytest.importorskip("docker")
pytest.importorskip("hy3_oj.sandbox.docker_executor")


@pytest.fixture(scope="module")
def executor():
    from hy3_oj.sandbox.docker_executor import DockerExecutor

    try:
        ex = DockerExecutor(load_config())
    except docker.errors.DockerException as e:
        pytest.skip(f"Docker 不可用（{type(e).__name__}）：请启动 Docker Desktop")
    try:
        if not ex.ping():
            pytest.skip("Docker Desktop 未启动")
        ex._client.images.get("gcc:13")
    except docker.errors.DockerException as e:
        pytest.skip(f"Docker 守护进程异常（{type(e).__name__}）：请重启 Docker Desktop")
    except docker.errors.ImageNotFound:
        pytest.skip("镜像 gcc:13 未拉取（docker pull gcc:13）")
    yield ex
    ex.close()


TESTS = [("3\n1 2 3\n", "6\n"), ("2\n10 20\n", "30\n")]


def _tests():
    from hy3_oj.core.schemas import TestCase

    return [TestCase(input=i, expected_output=o) for i, o in TESTS]


def test_ac(executor) -> None:
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);"
        "int n;cin>>n;long long s=0,x;while(n--){cin>>x;s+=x;}cout<<s<<'\\n';}\n"
    )
    results = executor.execute(Solution(code=code, language=Language.CPP17), _tests())
    assert all(r.verdict == Verdict.AC for r in results)


def test_wa(executor) -> None:
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\n"
        "int main(){int n;cin>>n;cout<<n<<'\\n';}\n"
    )
    results = executor.execute(Solution(code=code, language=Language.CPP17), _tests())
    assert all(r.verdict == Verdict.WA for r in results)


def test_compile_error(executor) -> None:
    code = "#include <bits/stdc++.h>\nint main(){ this is not c++ }\n"
    results = executor.execute(Solution(code=code, language=Language.CPP17), _tests()[:1])
    assert results[0].verdict == Verdict.CE
    assert "error" in results[0].stderr.lower()


def test_tle(executor) -> None:
    code = "#include <bits/stdc++.h>\nint main(){while(true){}}\n"
    results = executor.execute(Solution(code=code, language=Language.CPP17), _tests()[:1])
    assert results[0].verdict == Verdict.TLE


def test_re(executor) -> None:
    code = "#include <bits/stdc++.h>\nint main(){int* p=nullptr;*p=1;}\n"
    results = executor.execute(Solution(code=code, language=Language.CPP17), _tests()[:1])
    assert results[0].verdict == Verdict.RE
