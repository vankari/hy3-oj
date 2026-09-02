"""调试 loader 的 private 解码：逐环节打印。"""
from __future__ import annotations

import base64
import os
import pickle
import zlib

os.environ.setdefault("HF_HOME", "D:/hy3-oj-data/hf")

from datasets import load_dataset

from hy3_oj.data.loaders.livecodebench import _decode_private

ds = load_dataset("livecodebench/code_generation_lite", version_tag="release_v6", split="test", streaming=True, trust_remote_code=True)
row = next(iter(ds))
raw = row["private_test_cases"]
print("raw type:", type(raw), "len:", len(raw) if raw else 0)

blob = base64.b64decode(raw)
try:
    out = pickle.loads(zlib.decompress(blob))
    print("direct pickle: OK, type:", type(out), "len:", len(out) if isinstance(out, list) else "-")
    if isinstance(out, list):
        print("elem0 type:", type(out[0]), "keys:", out[0].keys() if isinstance(out[0], dict) else "-")
except Exception as e:
    print("direct pickle FAIL:", type(e).__name__, e)

res = _decode_private(raw)
print("loader _decode_private: len:", len(res))
