# Hy3-OJ：基于腾讯混元 Hy3 的算法竞赛智能解题与过程评估系统

> 本项目为 **2026 腾讯犀牛鸟开源人才培养计划「混元大语言模型」场景二（可验证场景：过程评估与错误定位）** 的个人/活动作品，非腾讯官方发布。
> 模型能力全程通过 **Hy3 API** 调用，不涉及训练或微调。

## 项目简介

Hy3-OJ 是一个算法竞赛端到端智能体系统：

- **自动解题**：输入题面，自动产出正确代码与完整解题过程（思路/复杂度/边界）；
- **闭环自纠错**：Docker 沙箱判题，按 CE/RE/WA/TLE 定向修复（≤N 轮），支持 C++17 兜底；
- **过程评估**（任务书核心）：五段式审查解题过程、定位错误步骤、归类错误类型、识别"答案正确但过程不成立"的蒙对样本；评估器经定位准确率与误报率验证；
- **文字题解**：面向初学者生成七节成文题解（题目重述→思路引导→算法步骤→正确性→复杂度→代码讲解→易错点）；
- **科学评测**：CodeContests / LiveCodeBench 上的 pass@k、过程正确率、错误类型分布与难度分层报告；
- **图形界面**：Streamlit 控制台，整合上述全部能力。

## 核心结果

| 数据集 | 基线（单轮直出） | 闭环 v10 |
|---|---|---|
| LiveCodeBench（60 题） | 30.0% | **81.7%**（easy 95% / medium 80% / hard 70%） |
| CodeContests（mid100） | — | 84%+ （持续评测中） |

过程评估有效性：定位准确率 **74%**（目标 ≥70%）、误报率 **0%**（目标 ≤20%）。

## 环境要求

- Python 3.11（推荐 `conda env create -f environment.yml`）
- Docker Desktop（沙箱判题，**必需**：判题与行为探针都依赖执行）
- 一个 Hy3 API Key（[TokenHub](https://console.cloud.tencent.com/tokenhub/inference)）

## 快速开始

```bash
conda env create -f environment.yml
conda activate hy3-oj
cp .env.example .env          # 填写 HY3_API_KEY（密钥禁止提交仓库）

docker pull python:3.11-slim  # Python 判题镜像
docker pull gcc:13            # C++17 兜底镜像（hard 档 TLE 攻坚）

python scripts/run_demo.py    # 启动图形界面 → http://localhost:8501
```

界面支持三种题目来源：上传 md/txt、粘贴文本、从数据集选题（`problems/` 下有示例）。

## 命令行用法

```bash
python scripts/run_solve.py --subset data/subsets/subset_lcb_v1.jsonl --out runs/closed_loop.jsonl
python scripts/run_explain.py --file problems/example_two_sum.md --out runs/explain/
python scripts/run_review.py --mode review --subset ... --solutions ... --out ...
python scripts/make_subset.py --total 300 --scan-limit 2000 --out data/subsets/subset_v1.jsonl
pytest tests/                 # 132 用例（Docker 未启动时容器相关自动 skip）
```

支持 Ctrl+C 优雅中断：不再开始新题，已完成结果全部保留，重跑自动续跑。

## 文档

| 文档 | 内容 |
|---|---|
| [方案设计](混元大语言模型-场景二算法竞赛方向-方案设计.md) | 总体方向：思路/架构/重点技术/预期效果/时间规划 |
| [项目架构设计](docs/项目架构设计.md) | folder 级模块设计、交互关系、算法思路、参考文献 |
| [PDF 任务书对齐](docs/pdf任务书对齐.md) | 任务书硬性要求 R1–R9 逐条对齐表 |
| [LiveCodeBench 报告 v10](docs/lcb_report_v10.md) | 60 题分层结果 + 版本演进 + 关键工程发现 |
| [过程评估报告](docs/process_evaluation_report.md) | R3–R8：五段式审查/定位准确率/误报率/蒙对案例 |
| [闭环消融报告](docs/ablation_report.md) | 基线 vs 闭环的模块增益拆解 |
| [GUI 设计](docs/gui_design.md) | 页面结构、布局、技术决策 |
| [演示脚本](docs/demo_script.md) | 2 分钟演示分镜（任务书 R9） |

## 目录结构

```
hy3_oj/
├── agents/     parser / planner / coder / tester / reflector / reviewer / explainer / prober
├── core/       pipeline(闭环状态机) / schemas(数据契约) / problem_io(外部题目) / checkpoint
├── data/       loaders(codecontests, livecodebench) / subset(分层抽样)
├── eval/       runner / metrics / report / process_eval
├── llm/        client(Hy3 唯一出口) / router(快慢思考) / pricing(成本计量)
├── sandbox/    docker_executor / judge / special_judge
├── prompts/    agent × 错误类型模板（yaml，版本化）
└── ui/         streamlit_app.py
```

## 已知限制

- **图片题面**：题面含图时为实验性支持——当前 API Key 未开通视觉模型，图片不会被解析，
  界面会如实标注「含 N 张图片未解析」，文字部分正常处理（不静默忽略）。
- **PDF**：需 `pymupdf`（未列入默认依赖，按需安装）；扫描件依赖视觉模型。
- **外部题目测试点**：未提供完整测试数据时，验证强度限于题面样例 + AI 生成测试（需暴力解验证），界面会明示强度。

## 安全与合规

- 密钥仅从环境变量/`.env` 读取，界面不提供输入框，仓库不含任何密钥（`.gitignore` 已覆盖）
- 所有生成代码在容器内执行：限时、限内存、断网、只读挂载

## AI 协作说明

本项目全程使用 CodeBuddy 辅助开发（契合本届 "Open with AI" 主题），协作细节记录于技术报告。
