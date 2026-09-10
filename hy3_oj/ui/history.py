"""对话持久化与旧版结果兼容。文件名只作内部标识，用户看到题目标题。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from hy3_oj.core.schemas import Conversation, ConversationMessage

# 模块级注册表跨 Streamlit rerun 保留，刷新后可重新连接同一后台任务。
JOBS: dict[str, dict] = {}


def title_from_text(text: str) -> str:
    lines = [re.sub(r"^[#\s>*-]+", "", line).strip() for line in text.splitlines()]
    line = next((line for line in lines if line and not line.startswith(("来源", "http"))), "新的解题")
    line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
    line = re.sub(r"[`$*_]", "", line).rstrip("：:")
    return line[:30] + ("…" if len(line) > 30 else "")


class HistoryStore:
    def __init__(self, ui_dir: Path):
        self.ui_dir = Path(ui_dir)
        self.directory = self.ui_dir / "conversations"

    def save(self, conversation: Conversation) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        dest = self.directory / f"{conversation.id}.json"
        tmp = dest.with_suffix(f".{uuid4().hex}.tmp")
        try:
            tmp.write_text(conversation.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)

    def new(self, title: str = "新的解题") -> Conversation:
        now = time.time()
        return Conversation(id=uuid4().hex, title=title, created_at=now, updated_at=now)

    def load(self, conversation_id: str) -> Conversation | None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", conversation_id):
            return None
        path = self.directory / f"{conversation_id}.json"
        if path.exists():
            try:
                return Conversation.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return next((c for c in self._legacy() if c.id == conversation_id), None)

    def list(self, query: str = "") -> list[Conversation]:
        records = {}
        for p in self.directory.glob("*.json"):
            try:
                c = Conversation.model_validate_json(p.read_text(encoding="utf-8"))
                records[c.id] = c
            except (OSError, ValueError):
                continue
        for c in self._legacy():
            records.setdefault(c.id, c)
        query = query.strip().casefold()
        return sorted((c for c in records.values() if query in c.title.casefold()),
                      key=lambda c: c.updated_at, reverse=True)

    def _legacy(self):
        for path in self.ui_dir.glob("*.json"):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(rec, dict) or "code" not in rec or "problem_id" not in rec:
                    continue
                pid = str(rec["problem_id"])
                text = rec.get("problem_statement") or rec.get("statement") or ""
                explanation_lines = (rec.get("explanation") or "").splitlines()
                description = next((line for line in explanation_lines if line.strip() and not line.startswith(("#", ">", "```"))), "")
                title = rec.get("title") or title_from_text(text or description or (
                    pid if not pid.startswith("_") else "历史解题（原题面未保存）"))
                stamp = path.stat().st_mtime
                cid = "legacy_" + hashlib.sha256(path.name.encode()).hexdigest()[:20]
                yield Conversation(id=cid, title=title, created_at=stamp, updated_at=stamp,
                    messages=[ConversationMessage(role="user", content=text or f"{title}\n\n旧记录未保存原始题面。"),
                              ConversationMessage(role="assistant", meta={"result": rec})])
            except (OSError, ValueError, TypeError):
                continue


def load_batch(path: Path) -> dict:
    """中断写入的最后一行不应让整份历史评测无法打开。"""
    recs = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict) or "problem_id" not in rec:
                raise ValueError("not a solve record")
            recs.append(rec)
        except ValueError:
            skipped += 1
    return {"n": len(recs), "passed": sum(bool(r.get("passed")) for r in recs),
            "recs": recs, "title": f"批量评测 · {len(recs)} 题", "skipped": skipped}
