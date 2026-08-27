# 单轮直出基线报告（冒烟子集，D3）

- 日期：2026-08-27 ｜ 模型：hy3（TokenHub，快思考模式，`thinking: disabled`）
- 子集：`data/subsets/subset_smoke.jsonl`（CodeContests train 分层抽样，seed=42，31 题）
- 方法：Coder 单轮直出（无规划、无闭环、无对拍），K=1，temperature=0.2
- 判题：Docker 一次性容器（python:3.11-slim），public+private+generated 全部测试点，限时 5s/512MB/断网

## 结果

| 难度 | pass@1 |
|---|---|
| easy (8) | **87.5%** (7/8) |
| medium (8) | **25.0%** (2/8) |
| hard (15) | **26.7%** (4/15) |
| **总体 (31)** | **41.9%** (13/31) |

## 失败类型分布

WA 11 ｜ TLE 5 ｜ RE 2

## 对预期指标的校准（方案文档 §5.1）

- easy 87.5% 基线已高于原预期（60%+），闭环+多路采样提升空间主要在中高档；
- medium 25% 与原预期一致；hard 26.7% 高于原预期（<10%），但样本仅 15 题，需 300 题正式集复核；
- WA 是最主要失败模式（11/18），印证 Reflector 反例构造 + 对拍预筛的优先级；
- TLE 5 例均在 medium/hard，对应 TLE→复杂度重分析的修复策略。

## 复现

```bash
python scripts/run_baseline.py --subset data/subsets/subset_smoke.jsonl --out runs/baseline_smoke.jsonl --concurrency 4
python scripts/summarize_results.py runs/baseline_smoke.jsonl
```
