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


def test_chat_page_starts() -> None:
    """当前单一对话页面能实际渲染，无需调用模型。"""
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    src = Path(__file__).resolve().parents[1] / "hy3_oj" / "ui" / "streamlit_app.py"
    app = AppTest.from_file(str(src)).run(timeout=15)
    assert not app.exception
    assert len(app.chat_input) == 1


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


def test_result_rejects_invalid_or_colliding_record(tmp_path, monkeypatch) -> None:
    from hy3_oj.ui import streamlit_app as app

    monkeypatch.setattr(app, "UI_DIR", tmp_path)
    app._save_result({"problem_id": "a/b", "code": "x"})
    assert app._load_result("a:b") is None
    for content in ("{", "[]"):
        (tmp_path / "broken.json").write_text(content, encoding="utf-8")
        assert app._load_result("broken") is None


def test_worker_only_updates_result_box(monkeypatch) -> None:
    from hy3_oj.ui import streamlit_app as app

    class NoSessionAccess:
        def __setattr__(self, name, value):
            raise AssertionError("worker must not write Streamlit session state")

    monkeypatch.setattr(app.st, "session_state", NoSessionAccess())
    monkeypatch.setattr(app, "run_app", lambda state: state["box"].update(result={"code": "x"}))
    box = {}
    app._run_graph_thread("text", None, None, box)
    assert box == {"result": {"code": "x"}, "done": True}


def test_review_failure_visible_even_when_tests_pass():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from hy3_oj.core.assessment import explanation_hash
    from hy3_oj.core.schemas import ReviewStep

    src = Path(__file__).resolve().parents[1] / "hy3_oj" / "ui" / "streamlit_app.py"
    app = AppTest.from_file(str(src)).run(timeout=15)
    app.session_state["messages"] = [{"role": "assistant", "meta": {"result": {
        "problem_id": "complexity-regression", "passed": True, "rounds": 1,
        "language_used": "python3", "code": "for a in range(100): pass",
        "review": {"process_score": 0.6, "error_step": "复杂度论证",
                   "explanation_sha256": explanation_hash("candidate analysis"),
                   "step_verdicts": [{"step": s.value, "passed": s != ReviewStep.COMPLEXITY_PROOF,
                                      "evidence": "O(N^0.5) exceeds O(N^0.25)"} for s in ReviewStep]},
        "explanation": "candidate analysis",
    }}}]
    app.run(timeout=15)
    assert not app.exception
    assert any("判题：AC" in e.value for e in app.markdown)
    assert any("结果通过 · 过程有误" in e.value for e in app.caption)
    assert any("$O(N^{0.5})$ exceeds $O(N^{0.25})$" in e.value for e in app.warning)


def test_no_key_input_in_ui() -> None:
    """界面不得出现密钥输入框（任务书硬性要求：密钥不落界面/仓库）。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "hy3_oj" / "ui" / "streamlit_app.py"
    text = src.read_text(encoding="utf-8")
    assert "text_input" in text  # 有输入框（题号），但…
    # 关键：不得有密钥相关的输入控件
    for forbidden in ('st.text_input("HY3', "api_key", "API Key 输入", 'type="password"'):
        assert forbidden not in text, f"界面不应包含 {forbidden}"
