"""D1 探测脚本：实测 Hy3（TokenHub）端点、快/慢思考参数（结果回填 configs）。

用法：conda activate hy3-oj; python scripts/probe_hy3.py
密钥从 .env 读取，不落盘输出。TokenHub 为国内端点，直连即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://tokenhub.tencentmaas.com/v1"
MODEL = "hy3"


def load_key() -> str:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HY3_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("HY3_API_KEY", "")


def main() -> None:
    key = load_key()
    if not key:
        sys.exit("HY3_API_KEY 未配置")
    client = OpenAI(api_key=key, base_url=BASE_URL, timeout=180)

    print("== chat.completions 基础调用 ==")
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "用一句话回答：1+1=?"}],
            max_tokens=256,
        )
        msg = r.choices[0].message
        print("content:", (msg.content or "")[:200])
        print("msg fields:", [f for f in msg.model_dump() if msg.model_dump()[f]])
        print("usage:", r.usage)
    except Exception as e:  # noqa: BLE001
        print("ERR", type(e).__name__, str(e)[:400])

    print("\n== 慢思考参数探测 ==")
    for label, kwargs in [
        ("enable_thinking=True", {"extra_body": {"enable_thinking": True}}),
        ("thinking=enabled", {"extra_body": {"thinking": {"type": "enabled"}}}),
        ("reasoning_effort=high", {"extra_body": {"reasoning_effort": "high"}}),
    ]:
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": "9.11 和 9.9 哪个大？只回答结论。"}],
                max_tokens=1024,
                **kwargs,
            )
            msg = r.choices[0].message
            dump = msg.model_dump()
            reasoning_keys = [k for k in dump if "reason" in k or "think" in k]
            print(f"[{label}] content={(msg.content or '')[:80]!r} reasoning_keys={reasoning_keys} usage={r.usage}")
        except Exception as e:  # noqa: BLE001
            print(f"[{label}] ERR {type(e).__name__} {str(e)[:300]}")

    print("\n== responses API 探测 ==")
    try:
        r = client.responses.create(model=MODEL, instructions="You are a helpful assistant.", input="你好", stream=False)
        print("output_text:", r.output_text[:200])
    except Exception as e:  # noqa: BLE001
        print("ERR", type(e).__name__, str(e)[:300])


if __name__ == "__main__":
    main()
