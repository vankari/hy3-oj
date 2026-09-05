"""探测：哪些视觉模型在该 key 下可用（OpenAI 兼容 base64 图片输入）。

逐个尝试候选模型，用极小 PNG + max_tokens=16，成本近乎为零。
输出每个模型的状态，确定外部题目图片解析可用路线。
"""
import base64
import struct
import zlib


def make_png(width: int = 32, height: int = 32, rgb: tuple[int, int, int] = (220, 40, 40)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


CANDIDATES = [
    "hunyuan-t1-vision-20250916",
    "deepseek/deepseek-v4-flash-vision-exp",
    "glm-5v-turbo",
    "hy-vision-2.0-instruct",
    "hy3",  # 对照：纯文本模型，预期不支持图片
]


def main() -> None:
    from pathlib import Path

    import httpx

    ROOT = Path(__file__).resolve().parents[1]
    key = ""
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("HY3_API_KEY="):
            key = line.split("=", 1)[1].strip()
    base = "https://tokenhub.tencentmaas.com/v1"
    uri = f"data:image/png;base64,{base64.b64encode(make_png()).decode()}"

    for model in CANDIDATES:
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "主色调？只答一个颜色词。"},
                    {"type": "image_url", "image_url": {"url": uri}},
                ],
            }],
            "max_tokens": 16,
        }
        try:
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json=payload, timeout=90)
            body = r.json()
            if r.status_code == 200:
                ans = body["choices"][0]["message"]["content"]
                print(f"[OK]   {model}: {ans.strip()[:40]!r} usage={body.get('usage')}")
            else:
                err = body.get("error", {})
                print(f"[FAIL] {model}: {err.get('code')} {str(err.get('message'))[:80]}")
        except Exception as e:  # noqa: BLE001
            print(f"[ERR]  {model}: {type(e).__name__} {str(e)[:60]}")


if __name__ == "__main__":
    main()
