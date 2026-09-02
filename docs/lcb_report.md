# LiveCodeBench 评测报告（任务书 R2 第二题集，防污染滚动基准）

> 日期：2026-09-01 ｜ 模型：hy3（TokenHub）｜ 管线：v3（hard 增强 + 暴力对拍 + top-2 修复 + 多解特判）
> 题集：`livecodebench/code_generation_lite` **release_v6**（= test.jsonl..test6.jsonl 累计 1055 题）

## 一、子集构造（任务书 R2 说明材料）

- 来源：LCB code_generation_lite release_v6（2023-05 起滚动收录，防训练污染设计）
- 构造：按 LCB 官方 difficulty 三桶均衡分层 + seed=42 随机抽样 60 题（easy 20 / medium 20 / hard 20）
- 平台分布自然混合：atcoder / leetcode / codeforces；其中 **call-based（LeetCode 风格）23 题**
- 每题测试：public ≤5 + private ≤20（pickle+zlib+base64 解码；判题完全本地可控）
- manifest：`data/subsets/subset_lcb_v1.manifest.json`

## 二、主结果（60 题）

| 难度 | 基线（单轮直出） | 闭环 v3 | 增益 |
|---|---|---|---|
| easy | 50.0% (10/20) | **90.0%** (18/20) | +40pt |
| medium | 40.0% (8/20) | **65.0%** (13/20) | +25pt |
| hard | **0.0%** (0/20) | **50.0%** (10/20) | +50pt |
| **总体** | **30.0%** (18/60) | **68.3%** (41/60) | **+38.3pt（2.28×）** |

- 平均收敛轮数（通过题）：0.5；token 总耗约 820 万（fast 758 万 / slow 63 万），单题约 13.7 万
  （v3 hard 档预算更高：k=10 + 深分析 + 6 轮修复）
- **hard 档基线全军覆没（0/20）而闭环救回一半（10/20）**——闭环价值在 LCB 高难度区间被放大；
  增益倍率 2.28× 与 AlphaCodium 在 CodeContests 上的 2.3× 高度一致
- call-based 适配（题面内嵌判题约定 + JSON 驱动模板）零异常跑通 23 题

## 三、过程评估（Reviewer v0.5）

| 指标 | 数值 |
|---|---|
| 过程正确率（LLM 语义层） | 74.6% (44/59) |
| R6 蒙对候选 | **0 题** |

LCB private 测试扎实（20/题 vs CodeContests 生成测试偏弱），"恰好通过弱测试"的蒙对
空间显著更小——0 候选与题集质量预期一致（对照：CodeContests mid100 有 p01811 实测铁证）。

## 四、与 CodeContests 对照

| | CodeContests mid100 | LCB 60 |
|---|---|---|
| 基线 | 49.0% | 30.0% |
| 闭环 | 70.0%（v3 重跑后 73%） | 68.3% |
| 增益 | +21pt（1.43×） | +38.3pt（2.28×） |
| hard 基线 | 30.0% | 0.0% |
| hard 闭环 | 52.0% | 50.0% |

- LCB 基线显著更低（题更新、hard 更硬、call-based 格式成本），闭环后两集闭环率相当——
  管线增益对"模型裸能力不足以直出"的题集更敏感
- 难度单调性在两集均成立，能力拐点稳定在 hard 档

## 五、工程备注

- LCB 无官方参考解：行为探针/多解特判/bug 注入验证在该集自动停用（宁缺毋滥），
  过程评估退回 LLM 语义层 + 人工抽检
- `arc183_c` 一题候选代码 segfault 杀崩 runner（exit 139）→ 已加固：容器非零退出归类 RE
  不再中断整批评测；runner 另加进程组整杀 + 总预算截断（177_F1 挂死教训）
- 数据缓存：HF 下载经 `hf_hub_download` 落盘（绕开官方脚本全量内存读的 MemoryError）；
  D 盘满时 `HY3_HF_CACHE` 环境变量可切缓存盘

## 复现

```bash
python scripts/make_subset_lcb.py --total 60 --out data/subsets/subset_lcb_v1.jsonl
python scripts/run_baseline.py --subset data/subsets/subset_lcb_v1.jsonl --out runs/baseline_lcb60.jsonl
python scripts/run_solve.py    --subset data/subsets/subset_lcb_v1.jsonl --out runs/closed_loop_lcb60.jsonl --concurrency 5
python scripts/run_review.py --mode review --subset data/subsets/subset_lcb_v1.jsonl --solutions runs/closed_loop_lcb60.jsonl --out runs/review_lcb60.jsonl
```
