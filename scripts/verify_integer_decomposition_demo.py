"""用真实 Docker 验证统一 1 秒时限下的两档数据，包含跨档慢解与 checker 回归。"""
import json
import time
from collections import Counter
from pathlib import Path

from hy3_oj.core.config import load_config
from hy3_oj.core.schemas import Language, Solution, TestCase, Verdict
from hy3_oj.data.subset import load_subset
from hy3_oj.sandbox.checkers import checker_source
from hy3_oj.sandbox.docker_executor import DockerExecutor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/demo/integer_decomposition"


def main():
    cfg = load_config()
    executor = DockerExecutor(cfg)
    checker = checker_source("integer_decomposition")
    records = []
    try:
        profiles = {name: load_subset(OUT / f"{name}_problem.jsonl")[0] for name in ("sqrt", "fourth")}
        assert all(p.judge.time_limit_s == 1.0 and p.judge.memory_mb == 256 for p in profiles.values())
        for profile, algorithm, lang, stress in [
            ("sqrt", "sqrt", "py", False), ("sqrt", "sqrt", "cpp", False),
            ("fourth", "fourth", "py", False), ("fourth", "fourth", "cpp", False),
            ("fourth", "sqrt", "py", True), ("fourth", "sqrt", "cpp", True),
            ("fourth", "blog_sqrt", "cpp", True),
        ]:
            problem = profiles[profile]
            tests = problem.public_tests + problem.private_tests
            if stress:
                max_n = max(int(t.input) for t in tests)
                tests = [t for t in tests if int(t.input) in (max_n-17, max_n-1009, max_n-1234567)]
            code = (OUT / f"reference_{algorithm}.{lang}").read_text(encoding="utf-8")
            start = time.monotonic()
            results = executor.with_limits(problem.judge).execute(
                Solution(code=code, language=Language.PYTHON3 if lang == "py" else Language.CPP17), tests, checker)
            counts = dict(Counter(r.verdict.value for r in results))
            record = {"profile": profile, "algorithm": algorithm, "language": lang,
                "cases": len(tests), "verdicts": counts, "max_time_ms": max(r.time_ms for r in results),
                "wall_seconds": round(time.monotonic()-start, 2),
                "limits": problem.judge.model_dump(), "stress_only": stress}
            record["failures"] = [{"n": t.input.strip(), "verdict": r.verdict.value}
                                   for t, r in zip(tests, results) if r.verdict != Verdict.AC]
            records.append(record)
            (OUT / "benchmark_in_progress.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
            print(json.dumps(record), flush=True)
            assert len(results) == len(tests)
            if stress:
                assert all(r.verdict == Verdict.TLE for r in results)
            else:
                assert all(r.verdict == Verdict.AC for r in results), counts
        ex = executor.with_limits(profiles["sqrt"].judge)
        # C++ 输出另一组最优三元组，也必须通过已注册 checker。
        other = Solution(language=Language.CPP17, code='#include <iostream>\nint main(){std::cout<<"13 10 0";}')
        assert ex.execute(other, [TestCase(input="130\n", expected_output="10 13 0\n")], checker)[0].verdict == Verdict.AC
        pairs = [("130\n", "13 10 0"), ("130\n", "11 11 9"), ("128\n", "9 14 2"),
                 ("130\n", "0 0 130"), ("130\n", "-10 -13 0"), ("130\n", "10 13 0 23"),
                 ("130\n", "10.0 13 0"), ("130\n", "")]
        checks = ex.run_checker(checker, pairs)
        assert checks == [True] + [False] * 7, checks
        (OUT / "benchmark.json").write_text(json.dumps({"runs": records, "checker_regressions": checks,
            "cpp_alternative_optimum": "AC", "cpu": "1 vCPU"}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        executor.close()


if __name__ == "__main__":
    main()
