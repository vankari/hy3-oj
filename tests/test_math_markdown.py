import pytest

from hy3_oj.ui.math_markdown import math_markdown


@pytest.mark.parametrize(("source", "expected"), [
    (r"约束：1 \le N \le 2 \times 10^5", r"约束：$1 \le N \le 2 \times 10^{5}$"),
    (r"S_i = \lbrace S_{i,1},\dots,S_{i,A_i} \rbrace.",
     r"$S_i = \lbrace S_{i,1},\dots,S_{i,A_i} \rbrace$."),
    ("复杂度O(sqrt(N))，要求O(N^(1/4))。", r"复杂度$O(\sqrt{N})$，要求$O(N^{1/4})$。"),
    ("O(N+M+sum A_i)", r"$O(N+M+\sum A_i)$"),
    ("A_10 和 N^0.25", r"$A_{10}$ 和 $N^{0.25}$"),
    ("(如 N^2)", r"(如 $N^{2}$)"),
    (r"\(N^{1/4}\)", r"$N^{1/4}$"),
    (r"\[a\times b+c=N\]", "\n\n$$\na\\times b+c=N\n$$\n\n"),
    ("上限5e5", r"上限$5 \times 10^{5}$"),
])
def test_math_formats(source, expected):
    assert math_markdown(source) == expected


@pytest.mark.parametrize("source", [
    "```python\nA_i = N ** 2\nprint('\\\\sum')\n```",
    "~~~text\nN^2 \\le M\n~~~",
    "`A_i` and ``literal ` N^2``",
    r"$N^{1/4}$ and $$\sum_{i=1}^{N} A_i$$",
    r"[原题 N^2](https://example.com/A_i?q=N^2)",
    r"https://example.com/A_i?q=N^2",
    r"runs/demo/merge_set/result.json",
    "hasM and error_step are identifiers, use C++17 or Python3.",
    "```python\nA_i = N ** 2",  # 尚未闭合的代码块
    "    A_i = N ** 2\n    B_i = M ** 2\n",
    "k > cnt2 and a = variable_name",
    "代码行24-27，样例1/2/3/4，日期2026-09-09。",
])
def test_code_links_and_existing_formulas_are_unchanged(source):
    assert math_markdown(source) == source


def test_mixed_text_is_idempotent():
    source = r"集合 S_i 和 $A_i$，满足 1 \le N；`S_i` 保持代码。"
    rendered = math_markdown(source)
    assert rendered == math_markdown(rendered)


def test_dataset_sample_preserves_input_lines():
    source = "Sample Input 1\n\n3 5\n2\n1 2\n\nSample Output 1\n\n2\n"
    rendered = math_markdown(source)
    assert "```text\n3 5\n2\n1 2\n```" in rendered
    assert "```text\n2\n```" in rendered


def test_sample_heading_inside_code_is_preserved():
    source = "```text\nSample Input 1\n3 5\n```"
    assert math_markdown(source) == source


def test_gui_renders_math_in_problem_and_explanation():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    src = Path(__file__).resolve().parents[1] / "hy3_oj/ui/streamlit_app.py"
    app = AppTest.from_file(str(src)).run()
    app.session_state["messages"] = [
        {"role": "user", "content": r"约束：1 \le N \le 10^5"},
        {"role": "assistant", "meta": {"result": {
            "problem_id": "math", "passed": True, "code": "A_i = N ** 2",
            "explanation": r"复杂度 O(N+sum A_i)。代码 `A_i`。",
        }}},
    ]
    app.run()
    assert not app.exception
    values = [m.value for m in app.markdown]
    assert r"约束：$1 \le N \le 10^{5}$" in values
    assert r"复杂度 $O(N+\sum A_i)$。代码 `A_i`。" in values
    assert app.code[0].value == "A_i = N ** 2"
