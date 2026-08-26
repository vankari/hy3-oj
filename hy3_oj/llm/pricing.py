"""token 成本计量：按题/阶段聚合，落盘 runs/metering.jsonl（帕累托分析数据源）。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_LOG = Path("runs/metering.jsonl")


def record(stage: str, mode: str, prompt_tokens: int, completion_tokens: int, reasoning_tokens: int, problem_id: str | None = None) -> None:
    """追加一条计量事件（线程安全，调用方异常不影响主流程）。"""
    event = {
        "ts": round(time.time(), 3),
        "stage": stage,
        "mode": mode,
        "problem_id": problem_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def summarize(log_path: str | Path = _LOG) -> dict:
    """聚合：按 mode / stage 统计 token 与调用次数。"""
    path = Path(log_path)
    if not path.exists():
        return {}
    by_mode: dict[str, dict] = {}
    by_stage: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        for bucket, key in ((by_mode, e["mode"]), (by_stage, e["stage"])):
            b = bucket.setdefault(key, {"calls": 0, "prompt": 0, "completion": 0, "reasoning": 0, "total": 0})
            b["calls"] += 1
            b["prompt"] += e["prompt_tokens"]
            b["completion"] += e["completion_tokens"]
            b["reasoning"] += e["reasoning_tokens"]
            b["total"] += e["total_tokens"]
    return {"by_mode": by_mode, "by_stage": by_stage}
