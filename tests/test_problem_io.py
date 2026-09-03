"""外部题目输入（md/txt）解析单测。"""
from __future__ import annotations

from pathlib import Path

from hy3_oj.core.problem_io import TEMPLATE, load_problem_file, load_problems_dir, write_template
from hy3_oj.core.schemas import Source

MD = """---
id: sum-three
difficulty: easy
tags: math, brute_force
constraints: 1 <= n <= 10
---

# 三数之和

给定 n 个整数，求它们的和。

## 输入

第一行 n，第二行 n 个整数。

## 输出

一个整数。

## 样例

```
3
1 2 3
```

```
6
```
"""

TXT = "Given two numbers a and b, output a+b.\n\nSample:\n```\n1 2\n```\n```\n3\n```\n"


def test_load_md_with_front_matter(tmp_path: Path) -> None:
    f = tmp_path / "p.md"
    f.write_text(MD, encoding="utf-8")
    p = load_problem_file(f)
    assert p.id == "sum-three"
    assert p.source == Source.EXTERNAL
    assert p.difficulty == "easy"
    assert p.tags == ["math", "brute_force"]
    assert p.constraints == "1 <= n <= 10"
    assert "三数之和" in p.statement
    assert len(p.samples) == 1
    assert p.samples[0].input.strip() == "3\n1 2 3"
    assert p.samples[0].expected_output.strip() == "6"


def test_load_txt_plain(tmp_path: Path) -> None:
    f = tmp_path / "p.txt"
    f.write_text(TXT, encoding="utf-8")
    p = load_problem_file(f)
    assert p.id == "p"  # 回退为文件名
    assert p.difficulty == "unknown"
    assert len(p.samples) == 1
    assert p.samples[0].expected_output.strip() == "3"


def test_no_front_matter(tmp_path: Path) -> None:
    f = tmp_path / "q.md"
    f.write_text("Just a statement without metadata.", encoding="utf-8")
    p = load_problem_file(f)
    assert p.id == "q"
    assert p.constraints == ""
    assert p.samples == []


def test_dir_batch_and_template(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(MD, encoding="utf-8")
    (tmp_path / "b.txt").write_text(TXT, encoding="utf-8")
    (tmp_path / "ignored.py").write_text("x=1", encoding="utf-8")
    problems = load_problems_dir(tmp_path)
    assert len(problems) == 2  # .py 被忽略

    t = write_template(tmp_path / "sub" / "tmpl.md")
    assert t.exists() and "## 样例" in t.read_text(encoding="utf-8")
    assert TEMPLATE.startswith("---")
