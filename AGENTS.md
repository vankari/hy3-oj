# AGENTS.md — 给代码智能体的项目上下文

> 本文件面向协作用代码智能体（CodeBuddy 等）：读完本文件即可理解项目目标、结构、约定与当前进度，直接开工。

## 1. 项目一句话

**Hy3-OJ**：基于腾讯混元 Hy3 API（快/慢思考融合）的算法竞赛端到端智能体——自动解题 + Docker 沙箱闭环自纠错 + **过程评估**（五段式审查/错误定位/错误归类/蒙对检测）+ 科学评测（CodeContests 优先，LiveCodeBench 后置）。
背景：2026 腾讯犀牛鸟开源人才培养计划「混元大语言模型」场景二，**个人/活动作品**，非官方发布；全程 API 调用，不训练/微调。

## 2. 必读文档（顺序）

1. `docs/pdf任务书对齐.md` — 任务书硬性要求 R1–R9 与逐条对齐表（**需求之源**，改动前先核对）
2. `混元大语言模型-场景二算法竞赛方向-方案设计.md` — 总体方向：思路/架构/重点技术/指标/时间规划
3. `docs/项目架构设计.md` — folder 级模块设计、交互关系、算法思路、参考文献（AlphaCodium/MapCoder/AlphaCode2/CodeContests+/Reflexion）

## 3. 目录速览

```
hy3_oj/core/      schemas.py(唯一数据契约,pydantic) pipeline.py(闭环状态机) config.py(yaml+env)
hy3_oj/llm/       client.py(Hy3 API 唯一出口) router.py(快慢思考调度) pricing.py(token 计量)
hy3_oj/agents/    parser planner coder tester reflector reviewer(过程评估器,任务书核心)
hy3_oj/sandbox/   docker_executor.py judge.py(已实现输出比对) cube_adapter.py(占位)
hy3_oj/data/      loaders/(codecontests 优先, livecodebench 后置) subset.py(分层抽样,seed=42)
hy3_oj/eval/      runner metrics.py(已实现 pass@k) process_eval.py(定位准确率/误报率) report
hy3_oj/prompts/   各 agent yaml 模板 + repair/{ce,re,wa,tle}.yaml（版本化管理）
hy3_oj/ui/        streamlit_app.py（后置）
scripts/          run_baseline / run_solve / run_eval / run_demo
tests/            test_schemas.py test_sandbox_smoke.py
configs/default.yaml   全部可调参数（模型名/采样/沙箱限额/评测目标）
```

## 4. 硬性约定（违反即返工）

1. **密钥零入库**：Hy3 key 只读环境变量 `HY3_API_KEY`（本地存 `.env`，已 gitignore）；任何 token/key 禁止出现在代码、yaml、md、commit message；新增配置样例只进 `.env.example`。
2. **模块间只传 `core/schemas.py` 的 pydantic 模型**，禁止字符串拼接口；schema 改动须同步 `SCHEMA_VERSION` 与单测。
3. **Agent 之间不直接通信**，由 `core/pipeline.py` 转发；每个 Agent 可独立单测。
4. **LLM 调用只走 `llm/client.py`**（重试/限流/缓存/计量），禁止在 Agent 内直接 new OpenAI client。
5. **提示词只放 `prompts/*.yaml`**（带 version 字段），消融实验改版本号而非改代码。
6. 一切 IO 落盘 `runs/`（轨迹 jsonl/计量/评测结果），保证断点续跑与复现。
7. 代码中的 `# TODO(Dx)` 对应 16 天排期（见方案文档第六章），按序推进；**D13 末功能冻结**。

## 5. 环境与常用命令

```powershell
conda activate hy3-oj          # Python 3.11；依赖见 requirements.txt / environment.yml
pytest tests/                  # 冒烟（Docker 未启动时沙箱用例自动 skip）
python scripts/run_solve.py --problem-id <id>
```

- 开发机为 Windows：沙箱**必须走 Docker 容器**（rlimit 不可用）；Docker Desktop 需手动启动。
- Hy3 快/慢思考的模型名/参数尚未实测：`configs/default.yaml` 中 `model_fast/model_slow` 为占位，实测后只改配置。

## 6. 当前进度（2026-08-26）

- [x] 方案文档 + 架构文档 + 任务书对齐；`hy3-oj` 环境；全量骨架（33 模块可导入，7 测试通过）
- [ ] D1–D3：Hy3 API 实测回填配置；CodeContests loader + 分层子集；单轮直出基线
- [ ] D4–D6：DockerExecutor + judge 校准（verdict 一致率 ≥99%）
- [ ] D7–D10：Agent 闭环 + Reviewer 过程评估器（五段式 + 蒙对规则已占位）
- [ ] D11–D13：全量评测 + 定位准确率/误报率验证 + Demo；D14–D16 收尾，9/11 交付

## 7. 常见坑

- 本机系统 `python` 指向 WindowsApps 占位，**必须用** `D:\ANACONDA\envs\hy3-oj\python.exe` 或先 activate。
- PowerShell 内联中文路径易乱码：涉及中文文件名的操作用脚本文件执行（UTF-8）。
- `deepmind/code_contests` 体积大：先 `subset.py` 分层抽样落盘再开发，别全量加载。
- AC 不等于结束：Reviewer 对 AC 解也要跑蒙对检测（任务书 R6）。
