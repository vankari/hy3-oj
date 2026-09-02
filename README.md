# Hy3-OJ：基于腾讯混元 Hy3 的算法竞赛智能解题与过程评估系统

> 本项目为 **2026 腾讯犀牛鸟开源人才培养计划「混元大语言模型」场景二（可验证场景：过程评估与错误定位）** 的个人/活动作品，非腾讯官方发布。
> 模型能力全程通过 **Hy3 API** 调用，不涉及训练或微调。

## 项目简介

Hy3-OJ 是一个算法竞赛端到端智能体系统：

- **自动解题**：输入题面，自动产出正确代码与完整解题过程（思路/复杂度/边界）；
- **闭环自纠错**：Docker 沙箱判题，按 CE/RE/WA/TLE 定向修复（≤N 轮）；
- **过程评估**（任务书核心）：五段式审查解题过程、定位错误步骤、归类错误类型、识别"答案正确但过程不成立"的蒙对样本；评估器经定位准确率与误报率验证；
- **科学评测**：CodeContests（优先）/ LiveCodeBench（后置）上的 pass@k、过程正确率、错误类型分布与难度分层报告。

## 环境要求

- Python 3.11（推荐 `conda env create -f environment.yml`）
- Docker Desktop（沙箱判题；Windows/macOS/Linux 均可）

## 安装与运行

```bash
conda env create -f environment.yml   # 或 conda create -n hy3-oj python=3.11 + pip install -r requirements.txt
conda activate hy3-oj

cp .env.example .env                  # 填写 HY3_API_KEY（密钥禁止提交仓库）

python scripts/run_baseline.py        # 单轮直出基线（D3 交付）
python scripts/run_solve.py           # 单题闭环解题（D7 交付）
python scripts/run_eval.py            # 子集评测与报告（D11 交付）
python scripts/run_demo.py            # Streamlit Demo（D11 交付）
pytest tests/                         # 冒烟测试
```

## 文档

- [方案设计文档](混元大语言模型-场景二算法竞赛方向-方案设计.md)：总体方向（思路/架构/重点技术/预期效果/时间规划）
- [项目架构设计](docs/项目架构设计.md)：folder 级模块设计、交互关系、算法思路、参考文献
- [PDF 任务书对齐](docs/pdf任务书对齐.md)：任务书硬性要求逐条对齐表
- [闭环消融报告](docs/ablation_report.md)：基线 vs 闭环（CodeContests 31 题冒烟 + 100 题扩展 + v3 增强）
- [过程评估报告](docs/process_evaluation_report.md)：任务书核心 R3–R8（五段式审查/定位准确率/误报率/蒙对案例）
- [LiveCodeBench 评测报告](docs/lcb_report.md)：第二题集 60 题（基线 30% → 闭环 68.3%）
- [人工抽检指南](docs/人工抽检指南.md)：human_verdict 填写规范（R7 误报率验证）

## AI 协作说明

本项目全程使用 CodeBuddy 辅助开发（契合本届 "Open with AI" 主题），协作细节将记录于技术报告。
