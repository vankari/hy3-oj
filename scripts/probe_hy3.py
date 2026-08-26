"""D1 探测脚本：实测 Hy3 API 端点、模型列表、快/慢思考参数（结果回填 configs）。

用法：conda activate hy3-oj; python scripts/probe_hy3.py
密钥从环境变量或 .env 读取，不落盘输出。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("HY3_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("HY3_API_KEY", "")


def main() -> None:
    key = load_env()
    if not key:
        sys.exit("HY3_API_KEY 未配置")
    base = "https://api.hunyuan.cloud.tencent.com/v1"
    headers = {"Authorization": f"Bearer {key}"}

    with httpx.Client(base_url=base, headers=headers, timeout=120) as c:
        # 1) 模型列表
        print("== GET /models ==")
        try:
            r = c.get("/models")
            print(r.status_code, json.dumps(r.json(), ensure_ascii=False)[:2000])
        except Exception as e:  # noqa: BLE001
            print("ERR", type(e).__name__, str(e)[:300])

        # 2) 基础对话（hy3-295b）
        print("\n== POST /chat/completions hy3-295b ==")
        payload = {
            "model": "hy3-295b",
            "messages": [{"role": "user", "content": "用一句话回答：1+1=?"}],
            "max_tokens": 512,
        }
        try:
            r = c.post("/chat/completions", json=payload)
            print(r.status_code, json.dumps(r.json(), ensure_ascii=False)[:1500])
        except Exception as e:  # noqa: BLE001
            print("ERR", type(e).__name__, str(e)[:300])

        # 3) 探测慢思考参数（常见命名逐一尝试，观察返回是否含 reasoning 字段）
        for extra in ({"enable_thinking": True}, {"thinking": {"type": "enabled"}}, {"reasoning_effort": "high"}):
            print(f"\n== slow-thinking probe: {extra} ==")
            try:
                r = c.post("/chat/completions", json={**payload, **extra})
                body = r.json()
                msg = body.get("choices", [{}])[0].get("message", {})
                print(r.status_code, "keys:", list(msg.keys()), "usage:", body.get("usage"))
            except Exception as e:  # noqa: BLE001
                print("ERR", type(e).__name__, str(e)[:300])


if __name__ == "__main__":
    main()
