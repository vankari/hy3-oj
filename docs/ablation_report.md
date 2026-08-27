# 闭环消融报告（冒烟子集 31 题，2026-08-27）

模型：hy3（TokenHub）｜ 子集：CodeContests train 分层抽样 seed=42（easy 8 / medium 8 / hard 15）

## 主结果

| 难度 | 基线(单轮直出) | 闭环 v1 | 闭环 v2(planner/reflector 修复) |
|---|---|---|---|
| easy (8) | 87.5% | 100% | **100%** |
| medium (8) | 25.0% | 37.5% | **37.5%** |
| hard (15) | 26.7% | 26.7% | **33.3%** |
| **总体** | 41.9% | 48.4% | **51.6%** |

## 模块增益拆解（v1→v2 对比）

| 模块 | 证据 | 增益 |
|---|---|---|
| K=6 采样 + 样例预筛 | v1 中 3 题 rounds=0 修复（1149_B / 1250_B / 284_B） | +6.5pt |
| Planner（v2 生效） | v1 全程 approach_n=0；v2 修复后 hard 档 26.7%→33.3% | hard +6.6pt |
| Reflector（v2 生效） | 经反思修复通过 4 题（1334_A / p01262 / professor-sharma / 1149_B），v1 为 0 | 破零 |

- 平均收敛轮数（通过题）：0.31（目标 ≤4，远超预期）
- 回退 1 题：substrings-count-3（K 采样方差，待 300 题复核）

## 关键工程发现（写入技术报告）

1. **慢思考模式不适合结构化输出**：hy3 慢思考把回复当 CoT 写，长输出被 max_tokens
   截断后永远到不了 JSON/代码块部分（v1 中 planner approach_n 全为 0、reflector 修复 0 成功）。
   → **结构化输出类 Agent（Planner/Reflector/Reviewer）必须走快思考**；
   慢思考仅适合"给自由文本推理过程"的场景（如 Reviewer 的证据引用分析）。
2. K 路采样 + 样例预筛是性价比最高的增益来源（零额外反思成本 +6.5pt）。
3. hard 题反思修复仍难：4 轮反思后仍 FAIL 的题多为算法选型层面的硬题，
   需要"换算法范式"级别的反思（TLE 模板已含此策略，WA 待强化）。

## token 成本（闭环 v2，31 题）

- 总调用 272 次（fast 225 / slow 47），总 token 约 53 万
- 单题平均约 1.7 万 token，约为基线的 10 倍 → 300 题正式集需先做成本预算与分层调度

## 复现

```bash
python scripts/run_baseline.py --subset data/subsets/subset_smoke.jsonl --out runs/baseline_smoke.jsonl
python scripts/run_solve.py   --subset data/subsets/subset_smoke.jsonl --out runs/closed_loop_v2.jsonl
python scripts/compare_ablation.py runs/baseline_smoke.jsonl runs/closed_loop_v2.jsonl
```
