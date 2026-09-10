import json

from hy3_oj.core.schemas import Conversation, ConversationMessage, SCHEMA_VERSION
from hy3_oj.ui.history import HistoryStore, load_batch


def test_conversation_roundtrip_and_same_title_do_not_overwrite(tmp_path):
    store = HistoryStore(tmp_path)
    first, second = store.new("整数分解"), store.new("整数分解")
    first.messages = [ConversationMessage(role="user", content="N > 100"),
                      ConversationMessage(role="assistant", meta={"result": {"code": "first", "explanation": "proof"}})]
    store.save(first)
    store.save(second)
    assert len(store.list()) == 2
    assert store.load(first.id) == first
    assert Conversation.model_validate_json(first.model_dump_json()).version == SCHEMA_VERSION
    assert len(store.list("整数")) == 2
    assert not store.list("missing")
    assert store.load("../../unsafe") is None


def test_legacy_and_corrupt_history(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "other.json").write_text("[]", encoding="utf-8")
    (tmp_path / "_paste.json").write_text(json.dumps({"problem_id": "_paste", "code": "x",
        "explanation": "## 1. 题目\n给定整数 N，寻找分解。"}, ensure_ascii=False), encoding="utf-8")
    store = HistoryStore(tmp_path)
    record, = store.list()
    assert record.title == "给定整数 N，寻找分解。"
    assert store.load(record.id) == record
    store.save(record)
    assert len(store.list()) == 1
    assert (tmp_path / "_paste.json").exists()


def test_truncated_batch_keeps_valid_records(tmp_path):
    p = tmp_path / "batch.jsonl"
    p.write_text('{"problem_id":"one","passed":true}\n{"problem_id":"two"}\n{', encoding="utf-8")
    result = load_batch(p)
    assert (result["n"], result["passed"], result["skipped"]) == (2, 1, 1)


def test_worker_saves_without_ui_polling(tmp_path, monkeypatch):
    from hy3_oj.ui import streamlit_app as app

    def fake_run(state):
        state["box"]["result"] = {"code": "answer", "passed": True}

    monkeypatch.setattr(app, "run_app", fake_run)
    store = HistoryStore(tmp_path)
    record = store.new("integer")
    record.messages = [ConversationMessage(role="user", content="problem")]
    record.status = "running"
    store.save(record)
    box = {}
    app._run_graph_thread("problem", None, None, box, record, tmp_path)
    saved = store.load(record.id)
    assert saved.status == "ready"
    assert saved.messages[-1].meta["result"]["code"] == "answer"
    assert box["done"]


def test_worker_failure_is_saved(tmp_path, monkeypatch):
    from hy3_oj.ui import streamlit_app as app

    def fail(state):
        raise RuntimeError("test unavailable")

    monkeypatch.setattr(app, "run_app", fail)
    record = HistoryStore(tmp_path).new("failure")
    box = {}
    app._run_graph_thread("problem", None, None, box, record, tmp_path)
    saved = HistoryStore(tmp_path).load(record.id)
    assert saved.status == "error"
    assert "test unavailable" in saved.messages[-1].meta["error"]
    assert box["done"]


def test_refresh_reconnects_empty_active_job(tmp_path, monkeypatch):
    from hy3_oj.ui import streamlit_app as app
    from hy3_oj.ui.history import JOBS

    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    monkeypatch.setattr(app.st, "session_state", State())
    monkeypatch.setattr(app.st, "query_params", {})
    record = HistoryStore(tmp_path).new("running")
    job = {}
    monkeypatch.setitem(JOBS, record.id, job)
    app._open_conversation(record)
    assert app.st.session_state.running
    assert app.st.session_state.result_box is job


def test_paste_routes_use_distinct_files_and_ids(tmp_path, monkeypatch):
    from hy3_oj.graph import orchestrator

    monkeypatch.setattr(orchestrator, "UI_DIR", tmp_path)
    _, first, _ = orchestrator.route_input("Given input N > 100, output a decomposition of N.", None)
    _, second, _ = orchestrator.route_input("Given input N > 100, output a decomposition of N.", None)
    assert first.id != second.id
    assert len(list((tmp_path / "inputs").glob("*.md"))) == 2


def test_history_click_refresh_and_new_chat(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from hy3_oj.ui import history

    real_store = HistoryStore
    monkeypatch.setattr(history, "HistoryStore", lambda _: real_store(tmp_path))
    store = real_store(tmp_path)
    record = store.new("整数分解示例")
    record.messages = [ConversationMessage(role="user", content="Find a decomposition"),
        ConversationMessage(role="assistant", meta={"result": {
            "problem_id": "test", "code": "print(123)", "passed": True, "explanation": "Saved explanation"}})]
    store.save(record)
    src = Path(__file__).resolve().parents[1] / "hy3_oj/ui/streamlit_app.py"
    app = AppTest.from_file(str(src)).run()
    app.button(key=f"history_{record.id}").click().run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert app.code[0].value == "print(123)"
    assert app.query_params["chat"] == [record.id]
    fresh = AppTest.from_file(str(src))
    fresh.query_params["chat"] = record.id
    fresh.run()
    assert fresh.code[0].value == "print(123)"
    fresh.button(key="new_chat").click().run()
    assert not fresh.chat_message
    assert store.load(record.id) is not None


def test_batch_details_can_be_opened_repeatedly(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from hy3_oj.ui import history

    real_store = HistoryStore
    monkeypatch.setattr(history, "HistoryStore", lambda _: real_store(tmp_path))
    src = Path(__file__).resolve().parents[1] / "hy3_oj/ui/streamlit_app.py"
    app = AppTest.from_file(str(src)).run()
    recs = [{"problem_id": str(i), "code": f"print({i})", "passed": True} for i in range(2)]
    app.session_state["messages"] = [{"role": "assistant", "meta": {
        "summary": {"n": 2, "passed": 2, "recs": recs}}}]
    app.run()
    assert not app.exception
    app.button(key="view_None_0_0").click().run()
    assert not app.exception
    assert app.code[0].value == "print(0)"
    cid = app.session_state["conversation_id"]
    app.button(key=f"view_{cid}_0_1").click().run()
    assert not app.exception
    assert [block.value for block in app.code] == ["print(0)", "print(1)"]


def test_chat_submit_saves_one_complete_conversation(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from hy3_oj.ui import history
    from hy3_oj.graph import orchestrator

    real_store = HistoryStore
    monkeypatch.setattr(history, "HistoryStore", lambda _: real_store(tmp_path))
    monkeypatch.setattr(orchestrator, "UI_DIR", tmp_path)

    def fake_run(state):
        assert "N > 100" in state["input_text"]
        state["box"]["result"] = {"problem_id": "demo", "code": "print(42)",
                                   "passed": False, "explanation": "saved demo"}

    monkeypatch.setattr(orchestrator, "run_app", fake_run)
    src = Path(__file__).resolve().parents[1] / "hy3_oj/ui/streamlit_app.py"
    app = AppTest.from_file(str(src)).run()
    assert not any(button.key == "demo_start" for button in app.button)
    app.chat_input[0].set_value("Given input N > 100, output a decomposition of N.").run(timeout=15)
    assert not app.exception
    record, = real_store(tmp_path).list()
    assert len(record.messages) == 2
    assert record.messages[0].role == "user"
    assert record.messages[1].meta["result"]["code"] == "print(42)"
    assert record.status == "ready"
