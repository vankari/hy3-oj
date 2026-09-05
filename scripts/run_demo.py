"""入口：启动 Streamlit 图形界面（任务书 R9 demo 载体）。

用法：
    python scripts/run_demo.py [--port 8501] [--no-browser]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "hy3_oj" / "ui" / "streamlit_app.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP),
        "--server.port", str(args.port),
        "--browser.gatherUsageStats", "false",
        "--theme.base", "light",
    ]
    if not args.no_browser:
        webbrowser.open_new_tab(f"http://localhost:{args.port}")
    print(f"启动 Streamlit: http://localhost:{args.port}")
    print("（若无 .env，请先复制 .env.example 为 .env 并填写 HY3_API_KEY）")
    raise SystemExit(subprocess.run(cmd, check=False, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
