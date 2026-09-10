"""LangGraph 顶层编排状态机（hy3-oj v0.6）。

设计：复用已成熟的 SolvePipeline 作为解题内核，外层用 graph 做鲁棒路由与超时兜底：
  classify     → single / batch / clarify（纯规则，无 LLM，瞬间）
  solve_single → pipeline.solve（带超时）+ 过程评估 reviewer + 题解 explainer
  solve_batch  → 逐题 solve（每题超时兜底），进度实时写回 box["progress"]
  clarify      → 友好提示，不进入解题（根治"你好"类输入卡死）

节点均为 async（SolvePipeline.solve 是 async）；UI 在独立线程用 asyncio.run(run_app(...)) 驱动。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from hy3_oj.core.config import load_config
from hy3_oj.core.problem_io import load_problem_file
from hy3_oj.core.schemas import Language, Problem, Solution, Source, Plan
from hy3_oj.core.pipeline import SolvePipeline
from hy3_oj.data.subset import load_subset

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "runs" / "ui"
UI_DIR.mkdir(parents=True, exist_ok=True)

# 超时（秒）：避免 LLM/判题异常导致无限卡死
SINGLE_TIMEOUT = 600
BATCH_PER_ITEM_TIMEOUT = 600

CLARIFY_HINT = (
    "未识别到有效题目。请粘贴竞赛题面（含输入/输出/样例/数据范围等），"
    "或点输入框 📎 上传 md/txt 题目文件，或上传 jsonl 子集做批量评测。"
)


class GraphState(TypedDict, total=False):
    input_text: str
    file_path: Optional[str]
    language: Optional[Language]
    problem: Optional[Problem]
    mode: Optional[str]            # single | batch | clarify
    result: Optional[dict]
    summary: Optional[dict]
    hint: Optional[str]
    error: Optional[str]
    box: dict                      # UI 轮询用（批量进度），原地更新


def _looks_like_problem(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 15:
        return False
    keys = ["输入", "输出", "样例", "给定", "求", "数据范围", "时间限制", "空间限制",
            "多组", "一行", "请问", "计算", "请输出", "array", "input", "output",
            "sample", "打印", "返回", "实现", "分析"]
    return any(k in t.lower() for k in keys)


def route_input(input_text, file_path):
    """纯规则路由：返回 (mode, problem_or_None, hint_or_None)。无 LLM，瞬间完成。"""
    if file_path:
        if str(file_path).endswith((".jsonl", ".json")):
            try:
                problems = load_subset(file_path)
            except (OSError, ValueError) as e:
                return ("clarify", None, f"题集解析失败：{e}")
            if not problems:
                return ("clarify", None, "题集为空，请上传包含题目的文件。")
            if len(problems) == 1:
                return ("single", problems[0], None)
            return ("batch", None, None)
        try:
            problem = load_problem_file(Path(file_path))
            return ("single", problem, None)
        except Exception as e:  # noqa: BLE001
            return ("clarify", None, f"题目文件解析失败：{e}。请检查 md/txt 格式。")
    text = input_text or ""
    if _looks_like_problem(text):
        tmp = UI_DIR / "inputs" / f"{uuid4().hex}.md"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        try:
            problem = load_problem_file(tmp)
        except Exception:
            problem = Problem(id="pasted", source=Source.EXTERNAL, statement=text,
                              difficulty="medium")
        return ("single", problem, None)
    return ("clarify", None, CLARIFY_HINT)


def classify(state: GraphState) -> GraphState:
    route, problem, hint = route_input(state.get("input_text"), state.get("file_path"))
    if route == "batch":
        return {"mode": "batch"}
    if route == "single":
        return {"mode": "single", "problem": problem}
    return {"mode": "clarify", "hint": hint}


def _read_plan(trace_file: str):
    try:
        for line in open(trace_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("state") in ("PLANNED", "PLAN") and e.get("plan"):
                return Plan(**e["plan"])
    except Exception:
        return None
    return None


def _judge_summary(cfg, problem, res) -> str:
    sb = problem.judge.model_dump() if problem.judge else cfg.get("sandbox", {})
    limits = f"每个测试限时 {sb.get('time_limit_s', 5)} 秒，容器内存上限 {sb.get('memory_mb', 512)} MB。"
    if not res["passed"]:
        return f"未通过（{res.get('rounds', 0)} 轮）。{limits}"
    count = len(problem.public_tests) + len(problem.private_tests) + len(problem.generated_tests)
    if problem.source == Source.EXTERNAL:
        scope = f"外部题提供的 {count} 个测试" if count else "外部题的 AI 生成测试"
    else:
        scope = f"{problem.source.value} 数据集的 {count} 个测试"
    return f"{scope}全部通过。{limits}"


async def _postprocess(cfg, problem, res):
    """Generate the explanation, then audit exactly that text without changing judge results."""
    from hy3_oj.agents import explainer, reviewer
    from hy3_oj.llm.client import Hy3Client
    from hy3_oj.core.assessment import assess, load_review_material

    plan = Plan(**res["plan"]) if res.get("plan") else _read_plan(res.get("trace_file", ""))
    solution = Solution(code=res["code"], language=res.get("language_used") or Language.PYTHON3)
    verdict = _judge_summary(cfg, problem, res)
    sb = problem.judge.model_dump() if problem.judge else cfg.get("sandbox", {})
    res["sandbox_limits"] = {"time_limit_s": sb.get("time_limit_s", 5), "memory_mb": sb.get("memory_mb", 512)}
    client = None
    rev = None
    try:
        client = Hy3Client(cfg)
        if not res.get("explanation"):
            res["explanation"] = await explainer.explain(
                client, problem, solution, plan=plan, judge_summary=verdict,
                language_hint="C++17" if solution.language == Language.CPP17 else "Python3",
            )
        if not res["explanation"].strip():
            raise ValueError("Empty explanation; process review cannot start")
        material = load_review_material(res["explanation"], res.get("trace_file", ""))
        rev = await reviewer.review(client, problem, plan, solution, "", material=material)
        res["review"] = rev.model_dump(mode="json")
        res["review"]["reviewer_version"] = reviewer.RULE_VERSION
    except Exception as e:
        res["review"] = {"error": f"{type(e).__name__}: {e}"}
    finally:
        if client is not None:
            await client.close()
    res["assessment"] = assess(res.get("passed"), rev, res.get("explanation", ""),
                                review_error=bool(res["review"].get("error"))).model_dump(mode="json")
    return res


async def solve_single(state: GraphState) -> GraphState:
    problem = state["problem"]
    lang = state.get("language")
    box = state.get("box")
    cfg = load_config()
    cfg["eval"]["runs_dir"] = str(UI_DIR / "jobs" / uuid4().hex)
    pipeline = SolvePipeline(cfg)
    # 把 trace 路径实时暴露给 UI，使其能像 GPT web 那样流式展示思考/工具调用
    tp = Path(cfg["eval"]["runs_dir"]) / "trace" / f"{SolvePipeline._safe_name(problem.id)}.jsonl"
    if box is not None:
        box["trace_path"] = str(tp)
    try:
        res = await asyncio.wait_for(
            pipeline.solve(problem, language=lang), timeout=SINGLE_TIMEOUT)
    except asyncio.TimeoutError:
        return {"error": f"单题解题超时（>{SINGLE_TIMEOUT}s），已中止以避免卡死。"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            await pipeline.client.close()
        except Exception:
            pass
        try:
            pipeline.executor.close()
        except Exception:
            pass
    try:
        res = await _postprocess(cfg, problem, res)
    except Exception as e:  # noqa: BLE001
        res["review"] = {"error": f"postprocess failed: {type(e).__name__}: {e}"}
    res["problem_statement"] = problem.statement
    return {"result": res}


async def solve_batch(state: GraphState) -> GraphState:
    fp = state["file_path"]
    lang = state.get("language")
    box = state.get("box")
    cfg = load_config()
    cfg["eval"]["runs_dir"] = str(UI_DIR / "jobs" / uuid4().hex)
    try:
        problems = load_subset(fp)
    except Exception as e:  # noqa: BLE001
        return {"error": f"子集读取失败：{e}"}
    pipeline = SolvePipeline(cfg)
    out = UI_DIR / f"batch_{uuid4().hex}.jsonl"
    recs: list[dict] = []
    try:
        for i, p in enumerate(problems, 1):
            try:
                rec = await asyncio.wait_for(
                    pipeline.solve(p, language=lang), timeout=BATCH_PER_ITEM_TIMEOUT)
            except asyncio.TimeoutError:
                rec = {"problem_id": p.id, "difficulty": p.difficulty,
                       "passed": False, "error": f"timeout>{BATCH_PER_ITEM_TIMEOUT}s"}
            except Exception as e:  # noqa: BLE001
                rec = {"problem_id": p.id, "difficulty": p.difficulty,
                       "passed": False, "error": f"{type(e).__name__}: {e}"}
            recs.append(rec)
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if box is not None:
                box["progress"] = {"i": i, "n": len(problems), "last": rec}
        n = len(problems)
        passed = sum(1 for r in recs if r.get("passed"))
        return {"summary": {"n": n, "passed": passed, "recs": recs,
                            "title": f"批量评测结果（{out.name}）", "out": str(out)}}
    finally:
        try:
            await pipeline.client.close()
        except Exception:
            pass
        try:
            pipeline.executor.close()
        except Exception:
            pass


def clarify(state: GraphState) -> GraphState:
    # hint 已在 classify 写入；graph 内 clarify 分支仅用于独立调用场景
    return {}


def _route(state: GraphState) -> str:
    return state.get("mode") or "clarify"


_APP = None


def _compile():
    g = StateGraph(GraphState)
    g.add_node("classify", classify)
    g.add_node("solve_single", solve_single)
    g.add_node("solve_batch", solve_batch)
    g.add_node("clarify", clarify)
    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", _route,
        {"single": "solve_single", "batch": "solve_batch", "clarify": "clarify"},
    )
    g.add_edge("solve_single", END)
    g.add_edge("solve_batch", END)
    g.add_edge("clarify", END)
    return g.compile()


def build_app():
    global _APP
    if _APP is None:
        _APP = _compile()
    return _APP


def run_app(state: dict) -> dict:
    """同步入口：在独立线程里 asyncio.run 驱动 graph。结果同步写回 box 供 UI 轮询。"""
    out = asyncio.run(build_app().ainvoke(state))
    box = state.get("box")
    if box is not None:
        if "error" in out:
            box["error"] = out["error"]
        elif "summary" in out:
            box["summary"] = out["summary"]
        elif "result" in out:
            box["result"] = out["result"]
        else:
            box["error"] = "未知结果（graph 未产出 result/summary/error）"
    return out
