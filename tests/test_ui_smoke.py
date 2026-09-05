"""Streamlit 界面冒烟：确保模块可导入、页面函数可调用（不启动服务）。

守护点：界面代码常因重构（函数改名/模块移动）而导入失败，
但这类问题只有启动服务才暴露——本测试把它提前到 CI。
"""
from __future__ import annotations


def test_import_app() -> None:
    """应用模块可导入（含 streamlit 依赖）。"""
    import importlib

    mod = importlib.import_module("hy3_oj.ui.streamlit_app")
    assert hasattr(mod, "main")


def test_pages_registered() -> None:
    """四个页面均已注册且可调用。"""
    from hy3_oj.ui import streamlit_app as app

    assert set(app.PAGES) == {"解题工作台", "评测看板", "人类反馈", "设置"}
    for name, fn in app.PAGES.items():
        assert callable(fn), name


def test_result_roundtrip(tmp_path, monkeypatch) -> None:
    """结果持久化可读写（刷新页面后能恢复上次结果）。"""
    from hy3_oj.ui import streamlit_app as app

    monkeypatch.setattr(app, "UI_DIR", tmp_path)
    rec = {"problem_id": "leetcode:3265", "passed": True, "code": "print(1)", "ts": 0.0}
    app._save_result(rec)
    assert app._load_result("leetcode:3265")["code"] == "print(1)"
    assert app._load_result("not-exist") is None


def test_result_filename_sanitized(tmp_path, monkeypatch) -> None:
    """题号含冒号/空格时文件名安全（Windows 非法字符）。"""
    from hy3_oj.ui import streamlit_app as app

    monkeypatch.setattr(app, "UI_DIR", tmp_path)
    app._save_result({"problem_id": "leetcode:3265 A/B", "code": "x", "ts": 0.0})
    assert app._load_result("leetcode:3265 A/B") is not None


def test_no_key_input_in_ui() -> None:
    """界面不得出现密钥输入框（任务书硬性要求：密钥不落界面/仓库）。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "hy3_oj" / "ui" / "streamlit_app.py"
    text = src.read_text(encoding="utf-8")
    assert "text_input" in text  # 有输入框（题号），但…
    # 关键：不得有密钥相关的输入控件
    for forbidden in ('st.text_input("HY3', "api_key", "API Key 输入", 'type="password"'):
        assert forbidden not in text, f"界面不应包含 {forbidden}"
