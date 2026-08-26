"""入口：启动 Streamlit Demo（D11 后置）。

用法：python scripts/run_demo.py  （等价于 streamlit run hy3_oj/ui/streamlit_app.py）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app = ROOT / "hy3_oj" / "ui" / "streamlit_app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)], check=False)


if __name__ == "__main__":
    main()
