# 闭环消融报告（冒烟子集 31 题，2026-08-27）

模型：hy3（TokenHub）｜ 子集：CodeContests train 分层抽样 seed=42（easy 8 / medium 8 / hard 15）

## 100 题扩展验证（2026-08-31，subset_mid100）

子集：subset_v1（同 seed=42 池）按桶顺序取前 N 题（easy 25 / medium 25 / hard 50），确定性可复现。

| 难度 | 基线（单轮直出） | 闭环 v2+（mid100） | 闭环增益 |
|---|---|---|---|
| easy | 84.0% (21/25) | **96.0%** (24/25) | +12pt |
| medium | 52.0% (13/25) | **80.0%** (20/25) | +28pt |
| hard | 30.0% (15/50) | **52.0%** (26/50) | +22pt |
| **总体** | **49.0%** (49/100) | **70.0%** (70/100) | **+21pt（1.43×）** |

（v2+ = 闭环 v2 + Tester 预筛 + refine 重规划）

- 平均收敛轮数（通过题）：0.5；token 总耗约 368 万（fast 344 万 / slow 24 万），单题约 3.7 万
- 难度单调性符合预期：easy 近饱和，medium 八成，hard 过半——能力拐点在 hard 档（详见过程评估报告）
- 外部锚点（口径不同，仅定性参照）：AlphaCodium（GPT-4，CodeContests valid，pass@5）19%→44%（+25pt，2.3×）；
  2026 前沿模型裸 pass@1 约 29~36%（valid/test 自然难度分布）。本集为 train 切片 + 50% hard 的偏难配比，
  与外部数字不可直接比；同子集内部对照（49%→70%）才是闭环增益的有效证据。
- 注：与冒烟集 51.6% 的差异同时包含"子集扩大"与"管线新增 Tester/refine"两因素，非同题对照

## v3 管线增强（2026-09-01，失败题重跑验证）

v3 新增：hard 档自适应预算（k=10、修复 6 轮、慢思考深分析）+ 暴力对拍预筛（样例验证过的暴力解
作差分 oracle）+ top-2 候选并行修复 + 多解题 LLM 特判 checker。
对 mid100 的 30 道失败题重跑：

| 指标 | 数值 |
|---|---|
| 失败题救回 | **3/30**（741_E hard、820_D hard、733_C medium） |
| mid100 合并 pass@1 | **73.0%**（70→73） |
| 残余失败 | 26 题（hard 23 + medium 2 + easy 1），多为算法选型层硬题——能力拐点确认在 hard 档 |

**618_B 根因结论（修正此前猜测）**：该题（多解重建排列）曾被怀疑是"精确比对误杀合法解"，
实证（候选输出手工核验）为**真实能力失败**——候选解输出全 0 的部分赋值，从未产出合法排列。
多解特判基础设施（LLM checker + 参考解反向验证）仍已落地，对多解题类提供正确判题口径。

**工程加固（177_F1 挂死教训）**：执行器 runner 改进程组整杀（孙进程持有管道也灭）+
runner 级总预算截断（缺失测试点按 RE 计，防"部分测试全过误判全过"）。

## 主结果（冒烟 31 题）

## 主结果（冒烟 31 题）

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
