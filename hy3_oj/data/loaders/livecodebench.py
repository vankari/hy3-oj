"""LiveCodeBench 加载器（防污染滚动基准，任务书 R2 第二题集）。

livecodebench/code_generation_lite → Problem schema：
- stdin/stdout 题（codeforces/atcoder 等）：测试用例直接可用；
- call-based 题（leetcode，starter_code 非空）：题面追加判题约定（类/方法签名 +
  stdin JSON 驱动模板），候选程序自带驱动入口；预期输出统一规范化为 canonical JSON
  （json/ast 双路解析），与驱动的 json.dumps 输出对齐；
- private_test_cases 官方约定为 pickle+zlib+base64，public 为明文 JSON；
- difficulty 直接用 LCB 标注（easy/medium/hard），作任务书 R2 分层依据；
- 版本钉死 version_tag（默认 release_v6），保证可复现。

注意：LCB 不含官方参考解 → reference_solutions 为空；行为探针/特判/bug 注入验证
在无参考解题上自动跳过（宁缺毋滥）。
"""
from __future__ import annotations

import ast
import base64
import json
import os
import pickle
import zlib
from collections.abc import Iterator
from typing import Any

from hy3_oj.core.schemas import Problem, Source, TestCase

MIN_STATEMENT_LEN = 100

# 每题测试点上限：LCB 部分题带数百个 private 测试（单题 blob 数百 KB），
# 全量解码在千题规模下会撑爆内存；判题 20 个 private 已足够覆盖
MAX_PUBLIC_TESTS = 5
MAX_PRIVATE_TESTS = 20

# call-based 判题约定模板（追加进题面；候选程序需自带该驱动入口）
_CALL_BASED_NOTICE = """
---
**判题约定（call-based）**：本题不读 stdin 逐行输入。请实现以下类与方法签名：

```python
{starter_code}
```

你的程序会被附加以下判题驱动后运行（驱动的 stdin 每个参数占一行 JSON，
逐行解析后按位置传参，以 canonical JSON 打印返回值）：

```python
if __name__ == "__main__":
    import json, sys
    lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
    try:
        args = [json.loads(l) for l in lines]
    except Exception:
        args = json.loads(sys.stdin.read())
    print(json.dumps(Solution().{func_name}(*args)))
```

请输出完整程序：开头 `from typing import *`（方法签名用了 List 等注解），
然后 class Solution 定义，最后原样附上上述驱动块。
"""


def _decode_private(raw: str) -> list[dict[str, Any]]:
    """private_test_cases 反序列化。

    官方实际结构（实测）：base64 → zlib → pickle → **JSON 字符串** → list。
    按 pickle → zlib+JSON → 明文 JSON 三路兜底，pickle 出 str 时再 json.loads 一层。
    """
    if not raw:
        return []
    try:
        blob = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return []
    for attempt in (
        lambda: pickle.loads(zlib.decompress(blob)),
        lambda: json.loads(zlib.decompress(blob).decode("utf-8")),
        lambda: json.loads(raw),
    ):
        try:
            out = attempt()
            if isinstance(out, str):
                out = json.loads(out)  # pickle 内层是 JSON 字符串（官方实测结构）
            if isinstance(out, list):
                return out
        except Exception:  # noqa: BLE001
            continue
    return []


def _norm_expected(output: str, functional: bool) -> str:
    """call-based 预期输出规范化：JSON/Python 字面量解析后重 dump，与驱动输出对齐。"""
    if not functional:
        return output
    for parser in (json.loads, ast.literal_eval):
        try:
            return json.dumps(parser(output))
        except Exception:  # noqa: BLE001
            continue
    return output


def _to_test_cases(cases: list[dict[str, Any]], functional: bool) -> list[TestCase]:
    tests = []
    for c in cases:
        inp, out = str(c.get("input", "")), str(c.get("output", ""))
        if not inp:
            continue
        tests.append(TestCase(
            input=inp if inp.endswith("\n") else inp + "\n",
            expected_output=_norm_expected(out, functional),
        ))
    return tests


def to_problem(raw: dict[str, Any]) -> Problem | None:
    """单条 LCB 记录 → Problem；缺测试或题面过短返回 None。"""
    statement = (raw.get("question_content") or "").strip()
    if len(statement) < MIN_STATEMENT_LEN:
        return None

    starter_code = (raw.get("starter_code") or "").strip()
    metadata = raw.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    func_name = (metadata or {}).get("func_name") or ""
    functional = bool(starter_code and func_name)

    public = raw.get("public_test_cases") or []
    if isinstance(public, str):
        try:
            public = json.loads(public)
        except json.JSONDecodeError:
            public = []
    private = _decode_private(raw.get("private_test_cases") or "")

    public_tests = _to_test_cases(public, functional)[:MAX_PUBLIC_TESTS]
    private_tests = _to_test_cases(private, functional)[:MAX_PRIVATE_TESTS]
    if not (public_tests or private_tests):
        return None

    if functional:
        statement = statement + _CALL_BASED_NOTICE.format(starter_code=starter_code, func_name=func_name)

    difficulty = str(raw.get("difficulty") or "").lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "hard"

    pid = f"{raw.get('platform', 'lcb')}:{raw.get('question_id') or raw.get('question_title', 'x')}"
    return Problem(
        id=pid,
        source=Source.LIVECODEBENCH,
        statement=statement,
        samples=public_tests[:3],
        difficulty=difficulty,
        tags=[str(raw.get("platform", ""))],
        public_tests=public_tests,
        private_tests=private_tests,
        generated_tests=[],
        reference_solutions=[],  # LCB 不含官方解；探针/特判/注入验证自动跳过
    )


def iter_problems(version_tag: str = "release_v6") -> Iterator[Problem]:
    """流式遍历 LCB。

    用 hf_hub_download 把版本 jsonl 落盘缓存后逐行读（避免官方 loading 脚本
    用 requests 全量读进内存的 MemoryError，千题 × 大 private blob 实测会炸）。
    版本语义与官方 loading 脚本一致：release_vN = test.jsonl .. testN.jsonl 累计拼接
    （各版本为增量时间窗）；HF 直连失败时设 HF_ENDPOINT 走镜像。
    """
    os.environ.setdefault("HF_HOME", "D:/hy3-oj-data/hf")
    from huggingface_hub import hf_hub_download

    # 缓存目录可被 HY3_HF_CACHE 覆盖（D 盘满时切 C 盘等）
    cache_dir = os.environ.get("HY3_HF_CACHE", "D:/hy3-oj-data/hf")
    n = int(version_tag.replace("release_v", ""))
    filenames = ["test.jsonl"] + [f"test{i}.jsonl" for i in range(2, n + 1)]
    for filename in filenames:
        path = hf_hub_download(
            "livecodebench/code_generation_lite", filename, repo_type="dataset",
            cache_dir=cache_dir,
        )
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                p = to_problem(json.loads(line))
                if p is not None:
                    yield p
