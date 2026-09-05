"""中断与检查点支持（对应方案：①优雅中断 ②阶段级 checkpoint 预留 ③人类反馈）。

三项能力：
1. 优雅中断（GracefulInterrupt）：Ctrl+C 时设置停止标志，当前题/批跑完即安全退出，
   已落盘结果不丢失（评测跑数小时，中断丢结果是真实痛点）。
2. 阶段级 checkpoint 接口（StageCheckpoint）：预留——当前 resume 是题级（jsonl append），
   单题内部跨阶段恢复待实现（见 save/load 的 TODO）。
3. 人类反馈（HumanFeedback）：结构化记录人对结果的判定，直接进报告与回归集。

设计原则：不阻塞流程。中断是协作式（cooperative）而非强制 kill，
保证"已完成的题不丢、正在跑的题可安全放弃"。
"""
from __future__ import annotations

import json
import signal
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


class GracefulInterrupt:
    """协作式中断：捕获 SIGINT/SIGTERM，置位 stopped，循环侧检查后安全退出。

    用法：
        gi = GracefulInterrupt()
        with gi:
            for p in problems:
                if gi.stopped:
                    break
                await solve(p)
    """

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._prev_handlers: dict[int, object] = {}

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def request_stop(self, signum=None, frame=None) -> None:
        """置位停止（可由信号或程序调用）。"""
        self._stopped.set()

    def reset(self) -> None:
        self._stopped.clear()

    def __enter__(self) -> GracefulInterrupt:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[sig] = signal.signal(sig, self._handler)
            except (ValueError, OSError):
                # 非主线程注册信号会失败（如 Streamlit 后台线程），降级为仅手动置位
                continue
        return self

    def _handler(self, signum, frame) -> None:
        self.request_stop(signum, frame)

    def __exit__(self, *exc) -> None:
        for sig, h in self._prev_handlers.items():
            try:
                signal.signal(sig, h)
            except (ValueError, OSError):
                pass
        self._prev_handlers.clear()


@dataclass
class StageCheckpoint:
    """阶段级检查点（接口预留）。

    当前 resume 为**题级**：结果逐题 append 落 jsonl，重跑跳过已完成题。
    单题内部（Parser→Planner→Coder→Judge）尚无跨阶段恢复，
    重跑一题会从 Parser 开始，重复消耗额度。

    本类预留接口，待实现时由 SolvePipeline 在各阶段后调用 save()，
    重跑时 load() 定位到断点阶段继续。
    """

    problem_id: str
    stage: str
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    @staticmethod
    def path(problem_id: str, runs_dir: str | Path = "runs") -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in problem_id)
        return Path(runs_dir) / "checkpoints" / f"{safe}.json"

    def save(self, runs_dir: str | Path = "runs") -> Path:
        p = self.path(self.problem_id, runs_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, problem_id: str, runs_dir: str | Path = "runs") -> StageCheckpoint | None:
        """读取检查点；不存在返回 None（调用方回退到全流程重跑）。"""
        p = cls.path(problem_id, runs_dir)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def clear(cls, problem_id: str, runs_dir: str | Path = "runs") -> None:
        """清除检查点（题目完成后调用）。"""
        cls.path(problem_id, runs_dir).unlink(missing_ok=True)


# ---------- ③ 人类反馈 ----------

VALID_VERDICTS = ("real", "false_positive", "unsure")


@dataclass
class HumanFeedback:
    """人对单条评估结论的判定（进报告与回归集）。

    verdict：
      real            —— 确认是真实问题（评估器判对）
      false_positive  —— 评估器误报（驱动 Reviewer 迭代的黄金数据）
      unsure          —— 存疑，不计入误报率分母
    """

    problem_id: str
    verdict: str
    note: str = ""
    reviewer: str = ""
    reviewer_version: str = ""
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(f"verdict 必须是 {VALID_VERDICTS} 之一，收到 {self.verdict!r}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts_human"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))
        return d


class FeedbackStore:
    """人类反馈存储（jsonl，追加式，可多人累积）。"""

    def __init__(self, path: str | Path = "runs/human_feedback.jsonl") -> None:
        self.path = Path(path)

    def add(self, fb: HumanFeedback) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fb.to_dict(), ensure_ascii=False) + "\n")

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def for_problem(self, problem_id: str) -> list[dict]:
        return [r for r in self.all() if r["problem_id"] == problem_id]

    def stats(self) -> dict:
        """误报率统计口径：只把 real / false_positive 计入分母（unsure 排除）。"""
        rows = self.all()
        counted = [r for r in rows if r["verdict"] in ("real", "false_positive")]
        fp = sum(1 for r in counted if r["verdict"] == "false_positive")
        return {
            "total": len(rows),
            "counted": len(counted),
            "unsure": len(rows) - len(counted),
            "false_positives": fp,
            "fp_rate": (fp / len(counted)) if counted else None,
        }
