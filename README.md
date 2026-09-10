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

演示视频与完整单题包见 [Demo 交付说明](docs/demo_delivery.md)：包含外部题和 LiveCodeBench hard 题的来源、固定测试构造、中文字幕视频及分片还原命令。

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
git clone https://github.com/vankari/hy3-oj.git
cd hy3-oj
conda env create -f environment.yml
conda activate hy3-oj
pip install -e . --no-deps   # 注册项目包，供 GUI / CLI 使用
cp .env.example .env          # 填写 HY3_API_KEY（密钥禁止提交仓库）

docker pull python:3.11-slim  # Python 判题镜像
docker pull gcc:13            # C++17 兜底镜像（hard 档 TLE 攻坚）

python scripts/run_demo.py    # 启动图形界面 → http://localhost:8501
```

启动前确保 Docker Desktop 已运行。配置与模型参数见 `configs/default.yaml`，密钥只填写到本地 `.env`。
无需 conda 时，可在 Python 3.11 虚拟环境中执行 `pip install -r requirements.txt` 和 `pip install -e . --no-deps`。
完整部署与故障排查见 [部署说明](docs/demo_script.md#部署说明环境搭建)。

界面支持粘贴文本、上传 md/txt 题面或包含测试的 JSONL 题包（`problems/` 下有示例）。
首次克隆不带全量数据集和运行历史；可按 [Demo 交付说明](docs/demo_delivery.md)还原完整演示题包直接上传。

## 命令行用法

```bash
python scripts/run_solve.py --subset data/subsets/subset_lcb_v1.jsonl --out runs/closed_loop.jsonl
python scripts/run_explain.py --file problems/example_two_sum.md --out runs/explain/
python scripts/run_review.py --mode review --subset ... --solutions ... --out ...
python scripts/make_subset.py --total 300 --scan-limit 2000 --out data/subsets/subset_v1.jsonl
pytest tests/                 # Docker 未启动时容器相关用例自动 skip
```

支持 Ctrl+C 优雅中断：不再开始新题，已完成结果全部保留，重跑自动续跑。

## 文档

建议先读任务书对齐和架构设计，复现演示时读部署脚本与交付说明。下表覆盖 `docs/` 下全部 Markdown 文档；评测报告保留各自实验版本和数据口径，历史结果不等同于当前成片的验收结果。

| 文档 | 内容梗概与用途 |
|---|---|
| [PDF 任务书对齐](docs/pdf任务书对齐.md) | 提炼任务书 R1–R9，逐条对应实现模块、验收指标与交付物；用于核对需求覆盖。 |
| [项目架构设计](docs/项目架构设计.md) | 说明目录职责、数据契约、Agent 编排、沙箱与评测数据流，附闭环状态机和相关论文；用于理解系统设计。 |
| [GUI 设计](docs/gui_design.md) | 说明对话工作区、题目输入、历史恢复、后台解题及结果展示的设计与实现取舍。 |
| [单轮基线报告](docs/baseline_report.md) | 记录冒烟子集的单轮直出结果、失败类型、成本及复现命令，为闭环增益提供对照。 |
| [闭环 v1 消融发现](docs/ablation_v1_findings.md) | 记录早期采样增益、规划与反思失效的根因、v2 修复和待验证假设；用于追溯迭代依据。 |
| [闭环消融报告](docs/ablation_report.md) | 汇总 31 题冒烟、100 题扩展和 v3 重跑，分析模块增益、工程问题、token 成本与复现步骤。 |
| [LiveCodeBench 早期报告](docs/lcb_report.md) | 说明 60 题子集构造、早期基线与闭环结果、过程评估及与 CodeContests 的对照，记录加载器适配细节。 |
| [LiveCodeBench 报告 v10](docs/lcb_report_v10.md) | 汇总 v10 的 60 题结果、难度分层、版本演进、残余失败原因与复现命令；对应视频批量看板的实验版本。 |
| [过程评估报告](docs/process_evaluation_report.md) | 围绕 R3–R8 介绍五段审查、错误定位与归类、蒙对案例、注入验证及人工抽检，说明定位准确率和误报率口径。 |
| [人工抽检指南](docs/人工抽检指南.md) | 定义真实错误、误报及不确定情况的判断标准，给出证据检查、反馈填写步骤与已核验判例。 |
| [整数分解测试数据说明](docs/integer_decomposition_dataset.md) | 说明博客题源、平方根与四次根两档题面、1 秒限制、确定性造测、独立标答核验、特殊校验器和在线反例。 |
| [Demo 候选题清单](docs/demo_problems.md) | 保存早期从两个数据集筛选的各难度候选题与运行命令；为历史备选清单，最终选题以交付说明为准。 |
| [演示脚本与部署](docs/demo_script.md) | 提供当前 1 分 58 秒成片分镜、题包复现、环境安装、密钥配置、Docker 启动和常见故障排查。 |
| [Demo 交付说明](docs/demo_delivery.md) | 说明最终两个样例的来源及名称、测试构造、在线验收、功能镜头、配图、视频分片还原和上传完整性检查。 |

总体研究目标、技术路线与排期另见根目录的 [方案设计](混元大语言模型-场景二算法竞赛方向-方案设计.md)。文档配图和字幕位于 `docs/assets/demo/`。

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
