# 闭环 v1 消融发现（2026-08-27）

## 数据（同一 31 题冒烟子集）

| 难度 | 基线 | 闭环 v1 |
|---|---|---|
| easy (8) | 87.5% | **100%** |
| medium (8) | 25.0% | **37.5%** |
| hard (15) | 26.7% | 26.7% |
| **总体** | 41.9% | **48.4%** (+6.5pt) |

## 关键发现

1. **增益来源是 K=6 采样 + 样例预筛，而非规划**：3 题修复（1149_B / 1250_B / 284_B）均为
   K 路采样中另有正确解被预筛选中，轨迹显示 `rounds=0`（未进反思即通过）。
2. **Planner 全程失效（严重 bug）**：所有轨迹 `approach_n=0`——慢思考模式下模型把回复
   当 CoT 写，长输出被 max_tokens 截断，永远到不了 JSON 部分。**结构化输出（Planner/Reflector）
   必须走快思考**（disabled thinking 输出直达内容，无 reasoning 占用）。
3. **反思修复 0 成功**：WA 题 4 轮反思仍全 WA，且诊断提取为空（同根因）。
4. **回退 1 题**（p00035）：题 id 含空格导致轨迹文件名非法（Windows），已修 `_safe_name`。
5. **成本**：闭环 token 约为基线 10 倍（K=6 采样 × 多轮反思），hard 题性价比低。

## 修复（v2）

- planner/reflector 改快思考 + `max_tokens=8192`（planner 验证 approach_n=8）
- `_extract_json` 支持 ```json 代码块提取
- reflector 诊断兜底用 reasoning 轨迹
- pipeline `_safe_name` 清洗非法文件名字符

## v2 待验证假设

- planner 生效后，规划能否带来超越纯采样的增益（medium/hard）
- reflector 快思考修复能否让"经反思修复通过题数"破 0
