"""Hy3-OJ 图形界面（Streamlit）。

任务书 R9 demo 载体：完整展示「题目输入 → 解题 → 判题 ⇄ 修复 → 过程评估 → 题解」。

设计见 docs/gui_design.md。关键约定：
- 密钥仅从环境变量/.env 读取，界面不提供输入框（任务书硬性要求）
- 复用既有模块，界面层只做编排与展示
- 长时间运行用 st.status 分步展示；「停止」按钮复用 GracefulInterrupt
- 结果落 runs/ui/<id>.json，刷新后可恢复
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import streamlit as st

from hy3_oj.core.checkpoint import FeedbackStore, GracefulInterrupt, HumanFeedback
from hy3_oj.core.problem_io import TEMPLATE, load_problem_file
from hy3_oj.core.schemas import Solution

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "runs" / "ui"
UI_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Hy3-OJ", page_icon="🧠", layout="wide")


def _lazy_pipeline():
    """延迟构造：避免导入即连 Docker/读 key（无 key 时页面仍可打开）。"""
    from hy3_oj.core.config import load_config
    from hy3_oj.core.pipeline import SolvePipeline

    return SolvePipeline(load_config()), load_config()


def _save_result(rec: dict) -> None:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in rec["problem_id"])
    (UI_DIR / f"{safe}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_result(problem_id: str) -> dict | None:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in problem_id)
    p = UI_DIR / f"{safe}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------- 页面：解题工作台 ----------------

def page_solve() -> None:
    st.title("🧠 解题工作台")
    st.caption("输入题目 → 一键解题 → 查看代码/判题/过程评估/题解")

    tab_file, tab_paste, tab_data = st.tabs(["📄 文件(md/txt)", "✍️ 粘贴文本", "📚 数据集选题"])

    problem = None
    warnings: list[str] = []

    with tab_file:
        up = st.file_uploader("上传题目文件", type=["md", "txt"])
        if up:
            tmp = Path(st.session_state.get("_tmp_dir") or (UI_DIR / "_upload"))
            tmp.mkdir(parents=True, exist_ok=True)
            f = tmp / up.name
            f.write_bytes(up.getvalue())
            try:
                problem = load_problem_file(f)
                st.success(f"已解析：{problem.id}（{problem.difficulty}）")
            except Exception as e:  # noqa: BLE001
                st.error(f"解析失败：{e}")
        if st.download_button("下载题目模板", TEMPLATE, file_name="problem_template.md"):
            pass

    with tab_paste:
        text = st.text_area("粘贴题面（支持 Markdown）", height=200,
                            placeholder="在这里粘贴题面…\n\n## 样例\n```\n输入\n```\n```\n输出\n```")
        if text.strip():
            tmp = UI_DIR / "_paste.md"
            tmp.write_text(text, encoding="utf-8")
            try:
                problem = load_problem_file(tmp)
                st.success(f"已解析：{problem.id}（{problem.difficulty}）")
            except Exception as e:  # noqa: BLE001
                st.error(f"解析失败：{e}")

    with tab_data:
        subsets = sorted((ROOT / "data" / "subsets").glob("*.jsonl"))
        if subsets:
            name = st.selectbox("选择评测子集", [s.name for s in subsets])
            if name:
                from hy3_oj.data.subset import load_subset

                probs = load_subset(ROOT / "data" / "subsets" / name)
                pid = st.selectbox("选择题号", [p.id for p in probs]) if probs else None
                if pid:
                    problem = next(p for p in probs if p.id == pid)
                    st.success(f"已载入：{problem.id}（{problem.difficulty}）")
        else:
            st.info("未找到子集，请先运行 scripts/make_subset.py")

    if problem is None:
        st.info("请先在上方输入题目")
        return

    # 解析结果告警（有限交互：只提示，不阻塞）
    if problem.constraints:
        st.caption(f"约束：{problem.constraints[:120]}")
    st.caption(f"识别样例：{len(problem.samples)} 组")
    if not problem.samples:
        warnings.append("未识别到样例 → 判题将无可用测试点（验证强度：弱）")
    if problem.difficulty == "unknown":
        warnings.append("未识别到难度 → 按 medium 处理")
    for w in warnings:
        st.warning(w, icon="⚠️")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        run = st.button("🚀 开始解题", type="primary", use_container_width=True)
    with col2:
        do_explain = st.checkbox("生成文字题解", value=True)
    with col3:
        if st.button("🛑 停止", use_container_width=True):
            st.session_state["_stop"] = True

    if run:
        st.session_state.pop("_stop", None)
        _run_solve(problem, do_explain)

    rec = _load_result(problem.id)
    if rec and not run:
        st.caption(f"（已载入上次结果：{time.strftime('%H:%M:%S', time.localtime(rec.get('ts', 0)))}）")
        _render_result(rec)


def _run_solve(problem, do_explain: bool) -> None:
    """执行解题全流程，分步展示进度。"""
    try:
        pipeline, cfg = _lazy_pipeline()
    except Exception as e:  # noqa: BLE001
        st.error(f"初始化失败（检查 .env 中 HY3_API_KEY 与 Docker 是否启动）：{e}")
        return

    gi = GracefulInterrupt()
    steps = st.status("解题中…", expanded=True)
    with steps:
        st.write("⚙️ 闭环执行中（解析 → 规划 → K 路生成 → 预筛 → 判题 ⇄ 修复）")
        if st.session_state.get("_stop"):
            st.warning("已请求停止")
            return
        t0 = time.time()
        try:
            # Streamlit 同步上下文：用 asyncio.run 驱动内部异步管线
            result = asyncio.run(pipeline.solve(problem))
        except Exception as e:  # noqa: BLE001
            st.error(f"解题失败：{type(e).__name__}: {e}")
            return
        finally:
            try:
                asyncio.run(pipeline.client.close())
            except Exception:  # noqa: BLE001
                pass
            pipeline.executor.close()

        result["elapsed_s"] = round(time.time() - t0, 1)
        result["ts"] = time.time()

        # 过程评估
        st.write("🔍 过程评估（五段式审查 + 蒙对检测）")
        try:
            from hy3_oj.agents import reviewer
            from hy3_oj.core.problem_io import load_problem_file  # noqa: F401
            from hy3_oj.core.schemas import Problem

            plan = None
            tf = Path(result.get("trace_file", ""))
            if tf.exists():
                for line in tf.read_text(encoding="utf-8").splitlines():
                    e = json.loads(line)
                    if e.get("state") in ("PLAN", "PLANNED") and "plan" in e:
                        from hy3_oj.core.schemas import Plan

                        plan = Plan(**e["plan"])
                        break
            verdict = ("AC（全部测试点通过）" if result["passed"]
                       else f"未通过（{result.get('rounds', 0)} 轮修复后仍失败）")
            from hy3_oj.core.config import load_config
            from hy3_oj.llm.client import Hy3Client
            from hy3_oj.sandbox.docker_executor import DockerExecutor

            cfg2 = load_config()
            client = Hy3Client(cfg2)
            ex = DockerExecutor(cfg2)
            try:
                rev = asyncio.run(reviewer.review(
                    client, problem, plan, Solution(code=result["code"]), verdict,
                    executor=ex, answer_passed=bool(result["passed"]),
                ))
                result["review"] = {
                    "process_score": rev.process_score,
                    "error_step": rev.error_step.value if rev.error_step else None,
                    "error_type": rev.error_type.value if rev.error_type else None,
                    "lucky_pass_flags": rev.lucky_pass_flags,
                    "step_verdicts": [{"step": sv.step.value, "passed": sv.passed,
                                       "evidence": sv.evidence} for sv in rev.step_verdicts],
                }
            finally:
                ex.close()
                asyncio.run(client.close())
        except Exception as e:  # noqa: BLE001
            st.warning(f"过程评估未执行：{type(e).__name__}: {e}")

        # 题解
        if do_explain:
            st.write("📝 生成文字题解")
            try:
                from hy3_oj.agents import explainer
                from hy3_oj.core.config import load_config
                from hy3_oj.llm.client import Hy3Client

                client = Hy3Client(load_config())
                try:
                    result["explanation"] = asyncio.run(explainer.explain(
                        client, problem, Solution(code=result["code"]),
                        judge_summary=("AC" if result["passed"] else "未通过"),
                    ))
                finally:
                    asyncio.run(client.close())
            except Exception as e:  # noqa: BLE001
                st.warning(f"题解生成失败：{type(e).__name__}: {e}")

        steps.update(label=f"{'✅ 通过' if result['passed'] else '❌ 未通过'}（{result['elapsed_s']}s）",
                     state="complete")

    _save_result(result)
    _render_result(result)


def _render_result(rec: dict) -> None:
    """渲染结果区（代码/判题/过程评估/题解 四个 tab）。"""
    t_code, t_judge, t_review, t_explain = st.tabs(["💻 代码", "⚖️ 判题", "🔍 过程评估", "📝 题解"])

    with t_code:
        st.code(rec.get("code", ""), language="python")
        st.caption(f"耗时 {rec.get('elapsed_s', '-')}s ｜ 修复轮数 {rec.get('rounds', '-')}")

    with t_judge:
        passed = rec.get("passed")
        st.markdown(f"### {'✅ 全部测试点通过' if passed else '❌ 未通过'}")
        if rec.get("error"):
            st.error(rec["error"])

    with t_review:
        rev = rec.get("review")
        if not rev:
            st.info("无过程评估记录")
        else:
            score = rev["process_score"]
            st.metric("过程评分", f"{score:.2f}")
            st.progress(min(max(score, 0.0), 1.0))
            if rev.get("lucky_pass_flags"):
                st.error(f"🚩 蒙对标记：{rev['lucky_pass_flags']}", icon="🚩")
            if rev.get("error_step"):
                st.warning(f"首个出错步骤：{rev['error_step']}（类型：{rev.get('error_type') or '—'}）")
            for sv in rev.get("step_verdicts", []):
                icon = "✅" if sv["passed"] else "❌"
                with st.expander(f"{icon} {sv['step']}"):
                    st.caption(sv.get("evidence", ""))

    with t_explain:
        if rec.get("explanation"):
            st.markdown(rec["explanation"])
        else:
            st.info("未生成题解（勾选「生成文字题解」后运行）")


# ---------------- 页面：评测看板 ----------------

def page_board() -> None:
    st.title("📊 评测看板")
    results = sorted((ROOT / "runs").glob("closed_loop_*.jsonl"))
    if not results:
        st.info("暂无评测结果（先运行 scripts/run_solve.py）")
        return
    name = st.selectbox("选择结果文件", [r.name for r in results])
    if not name:
        return
    recs = [json.loads(l) for l in (ROOT / "runs" / name).read_text(encoding="utf-8").splitlines() if l.strip()]
    n = len(recs)
    passed = sum(1 for r in recs if r.get("passed"))
    c1, c2, c3 = st.columns(3)
    c1.metric("题数", n)
    c2.metric("通过", passed)
    c3.metric("pass@1", f"{passed / n:.1%}" if n else "—")

    by_diff: dict[str, list] = {}
    for r in recs:
        by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
    st.subheader("分层结果")
    for d, rs in sorted(by_diff.items()):
        dp = sum(1 for r in rs if r.get("passed"))
        st.write(f"**{d}**：{dp}/{len(rs)} = {dp / len(rs):.1%}")
        st.progress(dp / len(rs) if rs else 0.0)


# ---------------- 页面：人类反馈 ----------------

def page_feedback() -> None:
    st.title("🙋 人类反馈")
    st.caption("对评估结论做人工判定（false_positive 数据是驱动评估器迭代的黄金样本）")
    store = FeedbackStore(ROOT / "runs" / "human_feedback.jsonl")

    pid = st.text_input("题号")
    verdict = st.radio("判定", ["real", "false_positive", "unsure"], horizontal=True)
    note = st.text_area("理由")
    if st.button("提交") and pid:
        store.add(HumanFeedback(problem_id=pid, verdict=verdict, note=note,
                                reviewer="ui", reviewer_version="v0.5"))
        st.success("已记录")

    stats = store.stats()
    st.subheader("统计")
    st.json(stats)
    rows = store.all()
    if rows:
        st.dataframe(rows[-20:], use_container_width=True)


# ---------------- 页面：设置 ----------------

def page_settings() -> None:
    st.title("⚙️ 设置")
    st.caption("密钥仅从环境变量/.env 读取，界面不提供输入（任务书硬性要求）")
    from hy3_oj.core.config import load_config

    cfg = load_config()
    st.json({
        "model": cfg["llm"].get("model"),
        "base_url_env": cfg["llm"].get("base_url_env"),
        "k_samples": cfg["solve"].get("k_samples"),
        "k_samples_medium": cfg["solve"].get("k_samples_medium"),
        "k_samples_hard": cfg["solve"].get("k_samples_hard"),
        "cpp_fallback": cfg["solve"].get("cpp_fallback"),
        "sandbox_image": cfg["sandbox"].get("image"),
        "cpp_image": cfg["sandbox"].get("cpp_image"),
    })
    import os

    key_set = bool(os.environ.get("HY3_API_KEY", "").strip())
    st.write("API Key 状态：", "✅ 已配置" if key_set else "❌ 未配置（请填写 .env）")


PAGES = {
    "解题工作台": page_solve,
    "评测看板": page_board,
    "人类反馈": page_feedback,
    "设置": page_settings,
}


def main() -> None:
    with st.sidebar:
        st.title("Hy3-OJ")
        st.caption("基于腾讯混元 Hy3 的算法竞赛智能解题与过程评估系统")
        page = st.radio("导航", list(PAGES))
        st.divider()
        st.caption("2026 犀牛鸟开源 · 个人/活动作品")
    PAGES[page]()


if __name__ == "__main__":
    main()
