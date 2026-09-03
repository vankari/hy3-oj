"""外部题目输入：把 md/txt 文件解析为 Problem。

支持两类外部题目来源（脱离固定数据集，供 Demo/App 使用）：
1. 纯文本题面（.txt/.md）：整段作为 statement，可选内嵌样例
2. 结构化 md：用 `## 输入` / `## 输出` / `## 样例` 等分节，或 YAML front-matter 指定约束与样例

约定（宽松解析，宁可少提取也不误伤）：
- 代码块 ``` 中的内容按出现顺序配对为 (输入, 输出) 样例
- front-matter 支持 id/difficulty/tags/constraints/source 字段
- 无法识别时退化为"整篇 statement + 无测试"，由 Coder 直出（人工再判）
"""
from __future__ import annotations

import re
from pathlib import Path

from hy3_oj.core.schemas import Problem, Source, TestCase

# ``` 代码块（含可选语言标记）
_CODE_BLOCK_RE = re.compile(r"```[\w+#-]*\s*\n(.*?)```", re.DOTALL)
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_SAMPLE_SECTION_RE = re.compile(r"##?\s*(样例|sample|examples?)[\s\S]*?(?=\n##?\s|\Z)", re.IGNORECASE)


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """提取 YAML-ish front-matter（极简解析：key: value 单行）。"""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[m.end():]


def _extract_samples(body: str) -> list[TestCase]:
    """从代码块中成对提取 (输入, 输出) 样例。

    策略：优先在「样例」小节内取代码块成对配对；否则全文取前两个代码块。
    """
    sec = _SAMPLE_SECTION_RE.search(body)
    target = sec.group(0) if sec else body
    blocks = [b.strip() for b in _CODE_BLOCK_RE.findall(target)]
    tests: list[TestCase] = []
    for i in range(0, len(blocks) - 1, 2):
        tests.append(TestCase(input=blocks[i] + "\n", expected_output=blocks[i + 1] + "\n"))
    if not tests and len(blocks) >= 2:
        tests.append(TestCase(input=blocks[0] + "\n", expected_output=blocks[1] + "\n"))
    return tests[:5]


def load_problem_file(path: str | Path, difficulty: str | None = None) -> Problem:
    """从 md/txt 文件加载 Problem。

    front-matter 可指定：id / difficulty / tags（逗号分隔）/ constraints / source
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(text)

    samples = _extract_samples(body)
    # statement 去掉 front-matter，保留全文（模型长上下文足够）
    statement = body.strip()

    tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
    return Problem(
        id=meta.get("id") or p.stem,
        source=Source.EXTERNAL,
        statement=statement,
        constraints=meta.get("constraints", ""),
        samples=samples,
        difficulty=difficulty or meta.get("difficulty") or "unknown",
        tags=tags,
        public_tests=samples,  # 外部题：样例即唯一可用测试（用于预筛）
    )


def load_problems_dir(dir_path: str | Path) -> list[Problem]:
    """批量加载目录下所有 .md/.txt 题目。"""
    d = Path(dir_path)
    files = sorted([*d.glob("*.md"), *d.glob("*.txt")])
    problems = []
    for f in files:
        try:
            problems.append(load_problem_file(f))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 跳过 {f.name}: {e}")
    return problems


# --- 题目模板（供用户填空，降低外部题门槛） ---

TEMPLATE = """---
id: my-problem-1
difficulty: easy
tags: dp, greedy
constraints: 1 ≤ n ≤ 2·10^5
---

# 题目名称

在这里写题面描述（支持 Markdown）。

## 输入

输入格式说明。

## 输出

输出格式说明。

## 样例

```
3
1 2 3
```

```
6
```
"""


def write_template(path: str | Path) -> Path:
    """写出题目模板文件（供用户填写）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(TEMPLATE, encoding="utf-8")
    return p
