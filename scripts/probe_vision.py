"""探测 TokenHub 可用模型列表（尤其视觉/多模态模型），GET /models 不耗额度。"""
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
key = ""
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("HY3_API_KEY="):
        key = line.split("=", 1)[1].strip()
base = os.environ.get("HY3_BASE_URL", "https://tokenhub.tencentmaas.com/v1")

r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=60)
print("status:", r.status_code)
if r.status_code != 200:
    print(r.text[:600])
    raise SystemExit(1)
data = r.json()
ids = sorted(m.get("id", "") for m in data.get("data", []))
print(f"models ({len(ids)}):")
for i in ids:
    print("  -", i)
# 分类提示
vision = [i for i in ids if any(k in i.lower() for k in ("vision", "vl", "image", "mm", "omni"))]
print("\nvision-like:", vision or "NONE")
text = [i for i in ids if any(k in i.lower() for k in ("hy3", "hy2", "hunyuan", "hy4"))]
print("text-like:", text)
