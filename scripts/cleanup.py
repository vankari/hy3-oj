"""清理缓存与无效文件（保留有价值的评测结果与报告）。

清理项：
- __pycache__ / .pytest_cache / *.pyc
- 临时诊断脚本（scripts/diag_*.py、scripts/debug_*.py、scripts/probe_*.py）
- 过期的中间版本结果（保留 v3 基线、v8/v10 关键版本与 *_dedup）
- runs/metering.jsonl 超长时截断保留最近 N 行
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
removed: list[str] = []
freed = 0


def rm(path: Path) -> None:
    global freed
    if not path.exists():
        return
    if path.is_dir():
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        shutil.rmtree(path, ignore_errors=True)
    else:
        size = path.stat().st_size
        path.unlink(missing_ok=True)
    freed += size
    removed.append(str(path.relative_to(ROOT)))


# 1) 缓存目录
for d in ROOT.rglob("__pycache__"):
    rm(d)
rm(ROOT / ".pytest_cache")

# 2) 临时诊断/调试脚本
for pat in ("diag_*.py", "debug_*.py", "probe_*.py", "stat_v*.py", "inspect_trace.py"):
    for f in (ROOT / "scripts").glob(pat):
        rm(f)

# 3) 过期中间结果（保留基线、v8、v10 与 dedup）
KEEP = {"baseline_lcb60", "closed_loop_lcb60", "closed_loop_lcb60_v8",
        "closed_loop_lcb60_v10", "closed_loop_v2", "review_smoke", "inject_smoke"}
runs = ROOT / "runs"
if runs.exists():
    for f in runs.glob("*.jsonl"):
        stem = f.stem.replace("_dedup", "")
        if stem not in KEEP and not stem.startswith("closed_loop_lcb60_v10"):
            rm(f)

# 4) metering 日志截断保留最近 20000 行
m = runs / "metering.jsonl"
if m.exists():
    lines = m.read_text(encoding="utf-8").splitlines()
    if len(lines) > 20000:
        m.write_text("\n".join(lines[-20000:]) + "\n", encoding="utf-8")
        removed.append(f"runs/metering.jsonl (truncated {len(lines)} -> 20000)")

print(f"removed {len(removed)} items, freed {freed / 1024 / 1024:.1f} MB")
for r in removed[:25]:
    print("  -", r)
if len(removed) > 25:
    print(f"  ... and {len(removed) - 25} more")
