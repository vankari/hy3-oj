"""为历史题面/题解补齐数学定界符；不改动代码、链接及已有 $ 公式。

数据集把网页转成纯文本后可能保留 TeX 命令却丢掉 $。仅转换可识别的
数学片段，未识别的自然语言保持原样，不修正公式本身的数学含义。
"""
from __future__ import annotations

import re


_PROTECTED = re.compile(
    r"(?m:^[ \t]{0,3}(?:`{3,}[^\n]*\n[\s\S]*?(?:^[ \t]{0,3}`{3,}[ \t]*$|\Z)"
    r"|~{3,}[^\n]*\n[\s\S]*?(?:^[ \t]{0,3}~{3,}[ \t]*$|\Z)))"
    r"|(?m:(?:^(?: {4}|\t)[^\n]*(?:\n|\Z))+)"
    r"|(?P<inline_code>`+)(?!`)[\s\S]*?(?<!`)(?P=inline_code)(?!`)"
    r"|!?\[[^\]\n]*\]\([^\n]*?\)"
    r"|https?://[^\s<>]+"
    r"|[\w./\\-]+\.(?:jsonl|json|py|cpp|md|txt|yaml|css)\b"
    r"|(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$"
    r"|(?<![\\$])\$(?!\$)[^$\n]+?(?<!\\)\$(?!\$)"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([^\n]*?\\\)"
    r"|(?m:^(?P<sample_title>Sample (?:Input|Output) \d+)\n+(?P<sample_body>[^\n]+(?:\n[^\n]+)*))"
)

_ATOM = r"(?:\\[a-zA-Z]+|(?:sqrt|floor|ceil|log2|log|sum|min|max)(?![a-zA-Z])|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[a-zA-Z](?![a-zA-Z]))"
_TOKEN = rf"(?:{_ATOM}|[+*/=^_{{}}(),<>|×≤≥√-])"
_BARE = re.compile(rf"(?<![a-zA-Z0-9_\\]){_ATOM}(?:[ \t]*{_TOKEN})*")
_MATH_HINT = re.compile(
    r"\\[a-zA-Z]+|[_^=<>≤≥×√]|\b(?:sqrt|floor|ceil|log2|log|sum)\b"
    r"|\bO\s*\(|\d[eE][+-]?\d|[\w}]\s*[+*/-]\s*[\w(\\]"
)


def _function_braces(text: str, name: str, opening: str, closing: str) -> str:
    """仅处理匹配成对括号的常见纯文本数学函数。"""
    pattern = re.compile(rf"(?<![\w\\]){name}\(")
    while match := pattern.search(text):
        depth = 1
        end = match.end()
        while end < len(text) and depth:
            depth += (text[end] == "(") - (text[end] == ")")
            end += 1
        if depth:
            break
        inner = text[match.end():end - 1]
        text = text[:match.start()] + opening + inner + closing + text[end:]
    return text


def _to_tex(text: str) -> str:
    text = _function_braces(text, "sqrt", r"\sqrt{", "}")
    text = _function_braces(text, "floor", r"\lfloor ", r"\rfloor")
    text = _function_braces(text, "ceil", r"\lceil ", r"\rceil")
    text = re.sub(r"([_^])\(([^()]*)\)", r"\1{\2}", text)
    text = re.sub(r"([_^])([+-]?\d+(?:\.\d+)?)", r"\1{\2}", text)
    text = re.sub(r"(?<![\w\\])sum(?=\s+[A-Za-z\\])", lambda _: r"\sum", text)
    text = re.sub(r"(?<![\w\\])log2\b", lambda _: r"\log_2", text)
    text = re.sub(r"(?<![\w\\])log\b", lambda _: r"\log", text)
    text = re.sub(r"(?<!\w)(\d+(?:\.\d+)?)[eE]([+-]?\d+)(?!\w)",
                  lambda m: m[1] + r" \times 10^{" + m[2] + "}", text)
    for source, target in (("<=", r"\le "), (">=", r"\ge "), ("≤", r"\le "),
                           ("≥", r"\ge "), ("×", r"\times ")):
        text = text.replace(source, target)
    return text


def _wrap_bare(text: str) -> str:
    def replace(match: re.Match) -> str:
        value = match.group()
        if not _MATH_HINT.search(value):
            return value
        if re.fullmatch(r"[\d\s.,/+\-]+", value):
            return value  # 行号范围、日期、样例编号不是算式
        # 自然语言紧跟的逗号、括号不属于公式。
        core = value.rstrip(" ,")
        while core.endswith(")") and core.count(")") > core.count("("):
            core = core[:-1].rstrip()
        if not core or core.count("{") != core.count("}") or core.count("(") != core.count(")"):
            return value
        if core[-1] in "=<>+*/^-_":
            return value  # 非数学标识符使表达式解析中止，不渲染半条等式
        return "$" + _to_tex(core) + "$" + value[len(core):]
    return _BARE.sub(replace, text)


def math_markdown(text: str) -> str:
    text = re.sub(r"\r+\n", "\n", text).replace("\r", "\n")
    parts = []
    end = 0
    for match in _PROTECTED.finditer(text):
        parts.append(_wrap_bare(text[end:match.start()]))
        value = match.group()
        if match.group("sample_title"):
            value = "#### " + match.group("sample_title") + "\n\n```text\n" + match.group("sample_body").strip() + "\n```\n"
        elif value.startswith(r"\["):
            value = "\n\n$$\n" + value[2:-2].strip() + "\n$$\n\n"
        elif value.startswith(r"\("):
            value = "$" + value[2:-2].strip() + "$"
        parts.append(value)
        end = match.end()
    parts.append(_wrap_bare(text[end:]))
    return "".join(parts)
