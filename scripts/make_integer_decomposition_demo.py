"""构造两档确定性外部题包；所有运行产物写入 runs/demo/integer_decomposition。

python scripts/make_integer_decomposition_demo.py
平方根基线为完整枚举；四次根实现采用苏剑林 archives/9775 的 p,q 参数化。
"""
from __future__ import annotations

import hashlib
import json
import random
from math import isqrt
from pathlib import Path

from hy3_oj.core.schemas import JudgeSpec, Problem, Source, TestCase
from hy3_oj.sandbox.checkers import checker_source
from hy3_oj.sandbox.checkers.integer_decomposition import optimal

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/demo/integer_decomposition"
BLOG = "https://spaces.ac.cn/archives/9775"

SQRT_CODE = '''from math import isqrt
import sys
n = int(sys.stdin.read())
best = (0, 0, n)
score = n
for a in range(1, isqrt(n) + 1):
    b, c = divmod(n, a)
    value = a + b + c
    if value < score:
        score, best = value, (a, b, c)
print(*best)
'''

CPP_HEADER = '''#include <bits/stdc++.h>
using namespace std;
using U = unsigned long long;
using W = __uint128_t;
U root(W n) {
    U x = sqrtl((long double)n);
    while (W(x+1)*(x+1) <= n) ++x;
    while (W(x)*x > n) --x;
    return x;
}
'''
SQRT_CPP = CPP_HEADER + '''int main() {
    U n; cin >> n; U score=n, aa=0, bb=0, cc=n;
    U limit=root(n);
    for(U a=1;a<=limit;++a){U b=n/a,c=n%a;
        if(a+b+c<score){score=a+b+c;aa=a;bb=b;cc=c;}}
    cout << aa << " " << bb << " " << cc << "\\n";
}
'''
FOURTH_CPP = CPP_HEADER + '''int main() {
    U n; cin>>n; U score=n,aa=0,bb=0,cc=n;
    auto consider = [&](U p) {
        W square=W(p)*p, four=W(4)*n;
        U q=0;
        if(square>four){W d=square-four;q=root(d);if(W(q)*q<d)++q;}
        if((p&1)!=(q&1))++q;
        U a=(p-q)/2,b=(p+q)/2,c=n-a*b;
        if(p+c<score){score=p+c;aa=a;bb=b;cc=c;}
    };
    U first=root(W(4)*n);consider(first);consider(first+1);
    for(U p=first+1;p<score;++p)consider(p);
    cout<<aa<<" "<<bb<<" "<<cc<<"\\n";
}
'''


def sqrt_optimal(n):
    best = (0, 0, n)
    for a in range(1, isqrt(n) + 1):
        b, c = divmod(n, a)
        if a + b + c < sum(best):
            best = a, b, c
    return best


def parity_oracle(n):
    """独立按 a,b 同/异奇偶枚举 x,y，交叉检查大整数 p,q 实现。"""
    def ceilroot(x):
        r = isqrt(x)
        return r + (r * r < x)
    bound = ceilroot(4*n) + 2 + ceilroot(1 + 4*ceilroot(n))
    best = n
    for x in range(max(0, isqrt(n)-1), bound//2+1):
        d = x*x - n
        y = ceilroot(d) if d > 0 else 0
        a, b = x-y, x+y
        if a >= 0:
            best = min(best, a+b+n-a*b)
        d = x*(x+1)-n
        y = (isqrt(1+4*d)-1)//2 if d > 0 else 0
        if y*(y+1) < d:
            y += 1
        a, b = x-y, x+y+1
        if a >= 0:
            best = min(best, a+b+n-a*b)
    return best


def build_cases(max_n):
    cases = {}
    def add(n, category):
        if 101 <= n <= max_n:
            cases.setdefault(n, category)
    for n in [101, 102, 103, 104, 107, 113, 127, 128, 129, 130, 131, 143, 144, 145, 169, 255, 256, 257]:
        add(n, "small_and_counterexamples")
    for root in [11, 31, 1009, isqrt(max_n)//2, isqrt(max_n)-1, isqrt(max_n)]:
        for delta in [-2, -1, 0, 1, 2]:
            add(root*root+delta, "square_boundary")
        for delta in [-1, 0, 1]:
            add(root*(root+1)+delta, "odd_sum_and_parity")
    rng = random.Random(9775)
    for _ in range(12):
        add(rng.randrange(max_n//2, max_n+1), "large_random")
    for offset in [0, 1, 2, 17, 1009, 1234567]:
        add(max_n-offset, "upper_boundary")
    if max_n >= 2**53:
        for n in [2**53-1, 2**53, 2**53+1, 2**53+3, 2**59-1, 2**59+1]:
            add(n, "float_precision")
    add(7489350167353676785, "online_window_counterexample")
    return cases


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 两个独立枚举实现检查所有小值，另以奇偶参数化检查大值。
    for n in range(101, 20001):
        assert sum(optimal(n)) == sum(sqrt_optimal(n)), n
    (OUT / "reference_sqrt.py").write_text(SQRT_CODE, encoding="utf-8")
    (OUT / "reference_fourth.py").write_text(checker_source("integer_decomposition") +
        '\nif __name__ == "__main__":\n    import sys\n    print(*optimal(int(sys.stdin.read())))\n', encoding="utf-8")
    (OUT / "reference_sqrt.cpp").write_text(SQRT_CPP, encoding="utf-8")
    (OUT / "reference_blog_sqrt.cpp").write_text(
        SQRT_CPP.replace("U a=1;", "U a=root(n/2)+1;"), encoding="utf-8")
    (OUT / "reference_fourth.cpp").write_text(FOURTH_CPP, encoding="utf-8")
    manifest = {"dataset_version": 2, "seed": 9775, "source": BLOG, "small_crosscheck": "101..20000", "profiles": {}}
    limit = 1.0
    for name, max_n in [("sqrt", 10**12), ("fourth", 2**63-1)]:
        cases = build_cases(max_n)
        public, private = [], []
        case_manifest = []
        directory = OUT / name
        directory.mkdir(exist_ok=True)
        for index, (n, category) in enumerate(cases.items(), 1):
            answer = optimal(n)
            assert sum(answer) == parity_oracle(n), n
            inp, expected = f"{n}\n", " ".join(map(str, answer)) + "\n"
            test = TestCase(input=inp, expected_output=expected)
            (public if n in (101, 128, 130, 144) else private).append(test)
            (directory / f"{index:03}.in").write_text(inp, encoding="utf-8")
            (directory / f"{index:03}.out").write_text(expected, encoding="utf-8")
            case_manifest.append({"n": n, "category": category, "minimum_sum": sum(answer)})
        title = "整数分解与最小和 · " + ("基础版" if name == "sqrt" else "大数据版")
        statement = f'''# {title}

给定整数 N，求非负整数 a、b、c，使 N = a × b + c，且 a + b + c 取得最小值。
若有多组最优解，输出任意一组。允许 a、b 交换。

## 输入
一行一个整数 N，101 ≤ N ≤ {max_n}。每个测试文件只有一组输入。

## 输出
一行三个十进制非负整数 a b c，以空格分隔。不输出额外说明或最小和值。
校验器检查等式成立、三个数非负以及 a+b+c 等于标准最小值，不要求三元组与标答逐字相同。

## 资源限制
每个测试限时 {limit:g} 秒，容器内存 256 MB。Python3 与 C++17 使用相同限制。

## 样例
```text
130
```
```text
10 13 0
```
最小和值为 23；13 10 0 也是合法输出。

```text
128
```
```text
8 16 0
```
最小和值为 24。

## 来源
依据苏剑林博客题意整理：{BLOG}
本项目将开放式“尽量小”表述明确为求最小值，并自行设计上述数据规模、时限和固定测试集。
'''
        problem = Problem(id=f"external:integer-decomposition-{name}", source=Source.EXTERNAL,
            statement=statement, constraints=f"101 <= N <= {max_n}; time={limit}s; memory=256MB",
            difficulty="medium" if name == "sqrt" else "hard", tags=["number_theory"],
            samples=public, public_tests=public, private_tests=private,
            judge=JudgeSpec(time_limit_s=limit, memory_mb=256, checker="integer_decomposition", tests_complete=True))
        pack = OUT / f"{name}_problem.jsonl"
        pack.write_text(problem.model_dump_json() + "\n", encoding="utf-8")
        (OUT / f"{name}_statement.md").write_text(statement, encoding="utf-8")
        manifest["profiles"][name] = {"max_n": max_n, "time_limit_s": limit, "memory_mb": 256,
            "public_tests": len(public), "private_tests": len(private), "cases": case_manifest,
            "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {x:y for x,y in v.items() if x != "cases"} for k,v in manifest["profiles"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
