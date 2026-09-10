"""Hy3-OJ 图形界面（Streamlit，对话为中心，类 ChatGPT/Claude）。

设计原则（参照 ChatGPT / Claude Web）：
- 单一对话界面：贴题 / 传题（输入框内嵌 📎）→ 系统自动跑完整 workflow：
  题意解析 → 算法规划 → 代码生成 → 判题 ⇄ 修复 → 过程评估 → 题解。
- 上传内嵌到输入框（不浮在顶部），像 ChatGPT 一样。
- 「评题」（过程评估 / 题解）是 workflow 的一环，不暴露为独立按键。
- 侧边栏按题目标题与时间分组展示对话，支持搜索和刷新恢复；批量记录折叠。
- 人类反馈放进结果卡的折叠区。

密钥仅从环境变量/.env 读取，界面不提供输入框。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import streamlit as st

from hy3_oj.core.checkpoint import FeedbackStore, HumanFeedback
from hy3_oj.core.schemas import Language, Conversation, ConversationMessage, ProcessReview, ProcessStatus, CombinedStatus
from hy3_oj.core.assessment import assess
from hy3_oj.graph.orchestrator import route_input, run_app
from hy3_oj.ui.history import HistoryStore, JOBS, title_from_text, load_batch
from hy3_oj.ui.math_markdown import math_markdown

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "runs" / "ui"
UI_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Hy3-OJ", page_icon="🧠", layout="wide")


# ---------------- 事件 → 友好文本 ----------------

def fmt_event(ev: dict) -> str | None:
    s = ev.get("state")
    if s == "JUDGE_CONFIG":
        limits = ev["judge"]
        return f"固定判题：{ev['tests']} 个测试 · {limits['time_limit_s']} 秒 / {limits['memory_mb']} MB"
    if s == "SPECIAL_JUDGE":
        return "🔎 检测到多解题，生成特判 checker"
    if s == "PARSED":
        return "📖 解析题意完成" + (f"（回退：{ev['warn']}）" if ev.get("warn") else "")
    if s == "DEEP_ANALYSIS":
        return "🧠 慢思考深度分析题意"
    if s in ("PLANNED", "PLAN"):
        plan = ev.get("plan") or {}
        tags = plan.get("algorithm_tags") or []
        return "🗺️ 规划算法：" + (", ".join(tags) if tags else "（默认策略）")
    if s in ("PLAN_DIVERGE", "PLAN_DIVERSE"):
        tags = ev.get("tags") or []
        flat = sum(tags, []) if tags and isinstance(tags[0], list) else (tags or [])
        return "🌿 多范式规划：" + (", ".join(flat) if flat else "（单一思路）")
    if s == "GENERATED":
        return f"💻 生成 {ev.get('k')} 份候选代码（难度 {ev.get('difficulty')}）"
    if s == "TEST_GEN":
        if ev.get("source") == "provided":
            return "已加载题目固定测试集，跳过 AI 测例生成"
        _nb = ev.get("n_boundary", ev.get("n", 0))
        _nf = ev.get("n_bf", 0)
        _b = "✓" if ev.get("brute") else "✗"
        return f"🧪 生成测试与暴力 oracle（边界 {_nb} + bf标答 {_nf}，brute {_b}）"
    if s == "LOCAL_TESTED":
        return f"✅ 预筛 top-{ev.get('top_k')} 进入全量判题"
    if s == "JUDGED":
        mark = "✅ 通过" if ev.get("passed") else "❌ 未过"
        return f"⚖️ 第 {ev.get('round')} 轮判题：候选 {ev.get('cand')} {mark}"
    if s == "CPP_FALLBACK":
        return "🔁 切换 C++17 再战一轮"
    if s == "REFINED":
        return f"🔧 重规划换范式：{ev.get('new_tags')}（保留最佳 {ev.get('kept_best_pass')} 测试点）"
    if s == "REFLECTED":
        return f"🤔 反思修复第 {ev.get('round')} 轮（{ev.get('pool')} 候选）"
    return None


def _submit(text: str, file_path: str | None, target_lang) -> None:
    """统一提交：同步路由（题面 / 批量 / 澄清）。澄清即时回复，其余交后台 graph。"""
    route, _problem, hint = route_input(text, file_path)
    label = text.strip() if text and text.strip() else (
        _problem.statement if _problem else f"上传题集：{Path(file_path).name}")
    st.session_state.messages.append({"role": "user", "content": label})
    store = HistoryStore(UI_DIR)
    current = store.load(st.session_state.get("conversation_id") or "")
    conversation = current or store.new(title_from_text(label))
    conversation.messages = [ConversationMessage(**m) for m in st.session_state.messages]
    conversation.updated_at = time.time()
    st.session_state.conversation_id = conversation.id
    st.query_params["chat"] = conversation.id
    if route == "clarify":
        st.session_state.messages.append({"role": "assistant", "meta": {"hint": hint}})
        conversation.messages.append(ConversationMessage(role="assistant", meta={"hint": hint}))
        store.save(conversation)
        st.rerun()
        return
    conversation.status = "running"
    store.save(conversation)
    st.session_state.running = True
    st.session_state.result_box = {}
    st.session_state.batch_mode = (route == "batch")
    JOBS[conversation.id] = st.session_state.result_box
    threading.Thread(
        target=_run_graph_thread,
        args=(text, file_path, target_lang, st.session_state.result_box, conversation, UI_DIR),
        daemon=True,
    ).start()
    st.rerun()


def _run_graph_thread(input_text, file_path, language, box: dict,
                      conversation: Conversation | None = None, ui_dir: Path | None = None) -> None:
    result = box
    try:
        # 完成标记由本线程在历史落盘后写入，graph 只写实时进度和结果。
        run_app({"input_text": input_text or "", "file_path": file_path,
                 "language": language, "box": result})
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        meta = {k: result[k] for k in ("error", "summary", "result") if k in result}
        if not meta:
            meta = {"error": "未获得解题结果，请重新提交。"}
        box.update(meta)
        if conversation is not None:
            conversation.messages.append(ConversationMessage(role="assistant", meta=meta))
            conversation.status = "error" if "error" in meta else "ready"
            conversation.updated_at = time.time()
            try:
                HistoryStore(ui_dir or UI_DIR).save(conversation)
                box["conversation"] = conversation.model_dump()
            except OSError as e:
                box["save_error"] = str(e)
        box["done"] = True


# ---------------- 保存 / 汇总 ----------------

def _save_result(rec: dict) -> None:
    pid = rec.get("problem_id", "unknown")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in pid)
    (UI_DIR / f"{safe}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_result(problem_id: str) -> dict | None:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in problem_id)
    try:
        rec = json.loads((UI_DIR / f"{safe}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("problem_id") == problem_id else None


def _render_summary(summary: dict, scope: str = "summary") -> None:
    n = summary.get("n", 0)
    passed = summary.get("passed", 0)
    st.markdown(f"### 📊 {summary.get('title', '评测汇总')}")
    if summary.get("skipped"):
        st.warning(f"有 {summary['skipped']} 条记录不完整，已显示其余有效结果。")
    c1, c2, c3 = st.columns(3)
    c1.metric("题数", n)
    c2.metric("通过", passed)
    c3.metric("pass@1", f"{passed / n:.1%}" if n else "—")

    recs = summary.get("recs", [])
    by_diff: dict[str, list] = {}
    for r in recs:
        by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
    for d, rs in sorted(by_diff.items(), key=lambda item: ({"easy": 0, "medium": 1, "hard": 2}.get(item[0], 3), item[0])):
        dp = sum(1 for r in rs if r.get("passed"))
        st.write(f"**{d}**：{dp}/{len(rs)} = {dp / len(rs):.1%}")
        st.progress(dp / len(rs) if rs else 0.0)

    st.divider()
    st.markdown("**逐题**（点「查看」在对话中展开完整解题轨迹与代码）")
    for index, r in enumerate(recs):
        col_a, col_b = st.columns([5, 1])
        with col_a:
            st.write(f"`{r.get('problem_id')}` · {r.get('difficulty')} · "
                     f"{'✅' if r.get('passed') else '❌'} · 修复 {r.get('rounds', 0)} 轮")
        with col_b:
            if st.button("查看", key=f"view_{scope}_{index}", disabled=st.session_state.get("running", False)):
                st.session_state.messages.append({"role": "assistant", "meta": {"result": r}})
                _persist_messages()
                st.rerun()


# ---------------- 渲染助手消息 ----------------

def _render_feedback(pid: str | None, scope: str = "", reviewer_version: str = "") -> None:
    if not pid:
        return
    fk = f"fb_{scope}_{pid}"
    if st.session_state.get(f"{fk}_done"):
        st.success("✅ 已记录反馈")
        return
    labels = {"确有问题": "real", "属于误报": "false_positive", "暂不确定": "unsure"}
    verdict = labels[st.radio("你怎么看这次审查？", list(labels), key=f"{fk}_v", horizontal=True)]
    note = st.text_input("理由（可选）", key=f"{fk}_n")
    if st.button("提交反馈", key=f"{fk}_b"):
        try:
            FeedbackStore(ROOT / "runs" / "human_feedback.jsonl").add(
                HumanFeedback(problem_id=pid, verdict=verdict, note=note,
                              reviewer="ui", reviewer_version=reviewer_version))
            st.session_state[f"{fk}_done"] = True
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"反馈保存失败：{e}")


def render_assistant(meta: dict, scope: str = "result") -> None:
    if meta.get("error"):
        st.error(f"执行失败：{meta['error']}")
        return
    if meta.get("hint"):
        st.info(meta["hint"])
        return
    if meta.get("summary") is not None:
        _render_summary(meta["summary"], scope)
        return
    r = meta.get("result") or {}
    if r.get("replay_note"):
        st.caption(r["replay_note"])
    verification = r.get("verification")
    if verification:
        source_label = {"external": "\u5916\u90e8\u9898", "livecodebench": "LiveCodeBench", "codecontests": "CodeContests"}.get(verification["source"], verification["source"])
        st.caption(f"{source_label} · 公开测试 {verification['public']} · "
                   f"私有测试 {verification['private']} · 通过 {verification['passed']}/{verification['total']}")
    passed = r.get("passed")
    lang = r.get("language_used") or ("cpp17" if r.get("code", "").lstrip().startswith("#include") else "python3")
    st.markdown(f"### 判题：{'AC' if passed else '未通过' if passed is False else '待判题'}")
    rev = r.get("review") or {}
    try:
        process_review = ProcessReview(**rev) if rev and not rev.get("error") else None
    except ValueError:
        process_review = None
    status = assess(passed, process_review, r.get("explanation", ""), review_error=bool(rev.get("error")))
    process_labels = {ProcessStatus.PASSED: "通过", ProcessStatus.FAILED: "有误",
                      ProcessStatus.PENDING: "待审查", ProcessStatus.ERROR: "审查异常"}
    combined_labels = {CombinedStatus.BOTH_PASSED: "结果通过 · 过程通过",
                       CombinedStatus.ANSWER_ONLY: "结果通过 · 过程有误",
                       CombinedStatus.PROCESS_ONLY: "结果未通过 · 过程通过",
                       CombinedStatus.BOTH_FAILED: "结果未通过 · 过程有误",
                       CombinedStatus.PENDING: "等待完整评估"}
    st.markdown(f"**过程审查：{process_labels[status.process_status]}**")
    st.caption(f"综合状态：{combined_labels[status.combined_status]}")
    if status.process_status == ProcessStatus.FAILED:
        st.warning("题解或解题过程存在问题，判题结果保持不变。")
        for sv in rev.get("step_verdicts", []):
            if not sv.get("passed", False):
                st.warning(math_markdown(f"{sv['step']}：{sv.get('evidence', '')}"))
    elif status.process_status == ProcessStatus.PENDING and rev:
        st.caption("已有审查未覆盖当前题解，需重新审查。")
    limits = r.get("sandbox_limits") or verification
    if limits and "time_limit_s" in limits and "memory_mb" in limits:
        st.caption(f"资源限制：每测试 {limits['time_limit_s']} 秒 · 容器内存 {limits['memory_mb']} MB")
    if lang:
        language_label = {"cpp17": "C++17", "python3": "Python3"}.get(lang, lang)
        st.caption(f"解题语言：{language_label}")
        if r.get("difficulty"): st.caption("\u96be\u5ea6\uff1a" + r["difficulty"])
    if r.get("language_advice"):
        st.info(f"💡 {r['language_advice']}")

    tf = r.get("trace_file")
    if tf and Path(tf).exists():
        with st.expander("🪜 解题轨迹", expanded=False):
            for line in open(tf, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                txt = fmt_event(ev)
                if txt:
                    st.markdown(f"- {txt}")

    t_explain, t_code, t_review = st.tabs(["题解", "代码", "过程评估"])
    with t_code:
        st.code(r.get("code", ""), language="python" if "py" in str(lang) else "cpp")
    if r.get("error"):
        st.error(r["error"])
    with t_review:
        rev = r.get("review")
        if not rev:
            st.info("无过程评估记录（批量评测默认不跑过程评估，可对该题单聊触发）")
        elif rev.get("error"):
            st.warning(f"过程评估未执行：{rev['error']}")
        else:
            score = rev.get("process_score", 0.0)
            st.metric("过程评分", f"{score:.2f}")
            st.progress(min(max(score, 0.0), 1.0))
            if rev.get("lucky_pass_flags"):
                st.error(f"🚩 蒙对标记：{rev['lucky_pass_flags']}")
            if rev.get("error_step"):
                st.warning(f"首个出错步骤：{rev['error_step']}（类型：{rev.get('error_type') or '—'}）")
            for sv in rev.get("step_verdicts", []):
                icon = "✅" if sv["passed"] else "❌"
                with st.expander(f"{icon} {sv['step']}"):
                    st.markdown(math_markdown(sv.get("evidence", "")))
    with t_explain:
        if r.get("explanation"):
            st.markdown(math_markdown(r["explanation"]))
        else:
            st.info("未生成题解")

    if r.get("review") and not r["review"].get("error"):
        with st.expander("反馈审查结果", expanded=False):
            _render_feedback(r.get("problem_id"), scope, r["review"].get("reviewer_version", "legacy"))


# ---------------- 对话主界面 ----------------

def _load_summary(path: Path) -> dict:
    return load_batch(path)


def _persist_messages() -> None:
    store = HistoryStore(UI_DIR)
    record = store.load(st.session_state.get("conversation_id") or "")
    if record is None:
        fallback = next((m.get("meta", {}).get("summary", {}).get("title")
                         for m in st.session_state.messages if m.get("meta", {}).get("summary")), "历史评测") or "历史评测"
        first = next((m.get("content", "") for m in st.session_state.messages if m["role"] == "user"), fallback)
        record = store.new(title_from_text(first))
        st.session_state.conversation_id = record.id
        st.query_params["chat"] = record.id
    record.messages = [ConversationMessage(**m) for m in st.session_state.messages]
    record.updated_at = time.time()
    record.status = "error" if record.messages and record.messages[-1].meta.get("error") else "ready"
    store.save(record)


def _open_conversation(record: Conversation) -> None:
    st.session_state.conversation_id = record.id
    st.session_state.messages = [m.model_dump() for m in record.messages]
    job = JOBS.get(record.id)
    st.session_state.result_box = job if job is not None else {}
    st.session_state.running = job is not None and not job.get("done", False)
    st.session_state.batch_mode = bool(job and job.get("progress"))
    st.query_params["chat"] = record.id


def _handle_upload(up, target_lang, text: str = ""):
    # 隔离同名上传，保留每次对话真正使用的题面。
    tmp = UI_DIR / "uploads" / uuid4().hex / Path(up.name).name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    payload = up.getbuffer()
    if text.strip() and tmp.suffix.lower() in (".md", ".txt"):
        payload = bytes(payload) + ("\n\n" + text).encode("utf-8")
    tmp.write_bytes(payload)
    _submit(text="", file_path=str(tmp), target_lang=target_lang)


def _complete_job() -> None:
    box = st.session_state.result_box
    if not box.get("done"):
        return
    if box.get("conversation"):
        record = Conversation(**box["conversation"])
        st.session_state.messages = [m.model_dump() for m in record.messages]
    else:
        meta = {k: box[k] for k in ("error", "summary", "result") if k in box}
        st.session_state.messages.append({"role": "assistant", "meta": meta})
        _persist_messages()
    if box.get("save_error"):
        st.session_state["save_warning"] = "历史记录保存失败，请检查磁盘空间。当前结果仍保留在页面中。"
    JOBS.pop(st.session_state.get("conversation_id"), None)
    st.session_state.running = False
    st.session_state.result_box = {}
    st.session_state.batch_mode = False


def page_chat(target_lang) -> None:
    if not st.session_state.messages:
        st.markdown('''<div class="hy-hero"><div class="hy-eyebrow">HY3-OJ · ALGORITHM WORKSPACE</div>
        <h1>一道题，从思路到验证。</h1>
        <p>写下你的问题。一起推敲算法、运行代码，<br>也检查答案背后的推理是否成立。</p></div>''', unsafe_allow_html=True)
        st.caption("在下方粘贴题面，或通过 + 上传题目。")
    else:
        for index, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(math_markdown(message["content"]))
                else:
                    render_assistant(message.get("meta", {}), scope=f"{st.session_state.get('conversation_id')}_{index}")

    if st.session_state.get("save_warning"):
        st.warning(st.session_state.save_warning)
    record = HistoryStore(UI_DIR).load(st.session_state.get("conversation_id") or "")
    if record and record.status == "running" and not st.session_state.running:
        st.warning("上次运行尚未完成，服务可能已重启。题面已保存，可重新提交。")

    if st.session_state.running:
        with st.chat_message("assistant"):
            box = st.session_state.result_box
            progress = box.get("progress")
            if progress:
                st.progress(progress["i"] / progress["n"], text=f"正在评测 · {progress['i']} / {progress['n']} 题")
            else:
                events = []
                trace = box.get("trace_path")
                if trace and Path(trace).exists():
                    for line in Path(trace).read_text(encoding="utf-8").splitlines():
                        try:
                            label = fmt_event(json.loads(line))
                            if label:
                                events.append(label)
                        except ValueError:
                            continue
                st.info(events[-1] if events else "正在理解题目并准备解题…")
                if events:
                    with st.expander("查看解题进度"):
                        for label in events:
                            st.write(label)
            st.caption("解题 → 测试与修复 → 过程评估 → 题解。完成后自动保存。")

    prompt = st.chat_input("粘贴题面，或通过 + 上传文件…", accept_file=True,
                           file_type=["md", "txt", "jsonl", "json"], disabled=st.session_state.running)
    if prompt is not None and not st.session_state.running:
        if isinstance(prompt, str):
            text, files = prompt, []
        else:
            text, files = prompt["text"] or "", prompt["files"] or []
        if files:
            _handle_upload(files[0], target_lang, text)
        elif text.strip():
            _submit(text, None, target_lang)
    if st.session_state.running:
        time.sleep(0.8)
        st.rerun()


def _sidebar() -> Language | None:
    store = HistoryStore(UI_DIR)
    with st.sidebar:
        st.markdown('<div class="hy-brand">Hy3<span>·</span>OJ</div>', unsafe_allow_html=True)
        st.caption("算法解题与过程评估")
        if st.button("＋ 新建对话", key="new_chat", use_container_width=True, disabled=st.session_state.running):
            st.session_state.messages = []
            st.session_state.conversation_id = None
            st.session_state.result_box = {}
            st.session_state.pop("save_warning", None)
            st.query_params.clear()
            st.rerun()
        query = st.text_input("搜索历史", placeholder="搜索题目…", label_visibility="collapsed", key="history_search")
        records = store.list(query)
        now = datetime.now().date()
        last_group = None
        for record in records:
            date = datetime.fromtimestamp(record.updated_at).date()
            group = "今天" if date == now else "昨天" if date == now - timedelta(days=1) else "近 7 天" if date >= now - timedelta(days=7) else "更早"
            if group != last_group:
                st.caption(group)
                last_group = group
            active = st.session_state.get("conversation_id") == record.id
            if st.button(record.title, key=f"history_{record.id}", use_container_width=True,
                         type="primary" if active else "secondary", disabled=st.session_state.running,
                         help=datetime.fromtimestamp(record.updated_at).strftime("%Y-%m-%d %H:%M")):
                _open_conversation(record)
                st.rerun()
        if not records:
            st.caption("没有匹配的对话" if query else "解题记录会保存在这里")

        with st.expander("解题偏好"):
            choice = st.radio("语言", ["自动选择", "Python3", "C++17"], key="language_choice", disabled=st.session_state.running)
        target_lang = {"自动选择": None, "Python3": Language.PYTHON3, "C++17": Language.CPP17}[choice]

        with st.expander("批量评测记录"):
            paths = sorted([*(ROOT / "runs").glob("closed_loop_*.jsonl"), *UI_DIR.glob("batch_*.jsonl")],
                           key=lambda p: p.stat().st_mtime, reverse=True)
            if not paths:
                st.caption("上传题集后，评测记录会出现在这里。")
            for index, path in enumerate(paths):
                date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m月%d日 %H:%M")
                if st.button(f"评测 · {date}", key=f"batch_{index}", disabled=st.session_state.running):
                    summary = _load_summary(path)
                    st.session_state.conversation_id = None
                    st.session_state.messages = [{"role": "assistant", "meta": {"summary": summary}}]
                    _persist_messages()
                    st.rerun()
        st.caption("由腾讯混元 Hy3 驱动 · 个人 / 活动作品")
    return target_lang


def main() -> None:
    st.markdown("<style>" + (Path(__file__).with_name("style.css")).read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
    defaults = {"messages": [], "running": False, "result_box": {}, "batch_mode": False, "conversation_id": None}
    first_load = "messages" not in st.session_state
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if first_load and st.query_params.get("chat"):
        record = HistoryStore(UI_DIR).load(st.query_params["chat"])
        if record:
            _open_conversation(record)
    _complete_job()
    page_chat(_sidebar())


if __name__ == "__main__":
    main()
