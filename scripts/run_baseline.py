"""入口：单轮直出基线（D1–D3）。

用法：python scripts/run_baseline.py --subset data/subsets/subset_v1.jsonl --out runs/baseline/
TODO(D3): 加载子集 → Coder 单次直出（无闭环）→ 判题 → pass@1 落盘，校准预期指标。
"""
from __future__ import annotations


def main() -> None:
    raise NotImplementedError("D3 实现：单轮直出基线")


if __name__ == "__main__":
    main()
