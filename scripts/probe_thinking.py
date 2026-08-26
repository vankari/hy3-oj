"""D1 补充探测：快/慢思考控制开关（对比 reasoning_tokens 与 reasoning_content 是否消失）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> tuple[str, str]:
    key = url = ""
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("HY3_API_KEY="):
            key = line.split("=", 1)[1].strip()
        elif line.startswith("HY3_BASE_URL="):
            url = line.split("=", 1)[1].strip()
    return key or os.environ.get("HY3_API_KEY", ""), url or "https://tokenhub.tencentmaas.com/v1"


def run(client: OpenAI, label: str, **kwargs) -> None:
    try:
        r = client.chat.completions.create(
            model="hy3",
            messages=[{"role": "user", "content": "9.11 和 9.9 哪个大？只回答结论。"}],
            max_tokens=1024,
            **kwargs,
        )
        msg = r.choices[0].message
        rc = getattr(msg, "reasoning_content", None)
        rt = r.usage.completion_tokens_details.reasoning_tokens if r.usage.completion_tokens_details else None
        out = {"label": label, "reasoning_tokens": rt, "has_reasoning_content": bool(rc), "answer": (msg.content or "")[:30]}
        print(str(out).encode("unicode_escape").decode()[:400])  # 避免 GBK 控制台乱码
    except Exception as e:  # noqa: BLE001
        print(f"[{label}] ERR {type(e).__name__} {str(e)[:200]}")


def main() -> None:
    key, base_url = load_env()
    client = OpenAI(api_key=key, base_url=base_url, timeout=180)
    run(client, "baseline")
    run(client, "enable_thinking=False", extra_body={"enable_thinking": False})
    run(client, "chat_template_kwargs.enable_thinking=False", extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    run(client, "thinking=disabled", extra_body={"thinking": {"type": "disabled"}})
    run(client, "reasoning_effort=low", extra_body={"reasoning_effort": "low"})


if __name__ == "__main__":
    main()
