# 演示脚本（≤2 分钟，任务书 R9）

已完成 1 分 58 秒真实应用录屏，含中文字幕与旁白。
当前成片的题源、测试构造与交付文件见 [Demo 交付说明](demo_delivery.md)。
首页保留通用输入区，演示时手动上传题包。

## 当前成片分镜

| 时段 | 画面 / 操作 | 说明 |
|---|---|---|
| 00:00–00:13 | 工作区、输入澄清 | 不完整题面先澄清 |
| 00:13–00:22 | 外部题包上传、C++17 选择 | 苏剑林博客题，平方根基础版 |
| 00:22–00:31 | 固定测试与自动解题 | seed=9775，边界/反例/随机数，交叉核验标答 |
| 00:31–00:39 | 外部判题结果 | 1 秒 / 256 MB，75/75 |
| 00:39–00:49 | 公式题解与五段审查 | 审题意、算法、复杂度、边界和实现一致性 |
| 00:49–00:58 | 内部题包上传 | 支持 CodeContests / LiveCodeBench，本次来自后者 |
| 00:58–01:10 | Merge Set 代码与结果 | ABC302 F，解释集合合并题名，数据集 16/16 |
| 01:10–01:28 | AI 造测、修复、过程错误 | 真实历史回放；判题 AC 与过程状态独立 |
| 01:28–01:41 | 人工反馈、历史搜索与刷新 | 反馈落盘，刷新后恢复对话 |
| 01:41–01:58 | 批量看板、难度分层、逐题详情、收尾 | 已有 LiveCodeBench 60 题评测记录 |

两条正向样例已通过真实浏览器在线复测，过程审查也通过。拍摄使用正常缓存复跑；等待加速和历史回放均在片中标注。
外部基础版为本项目固定测试，不走 AI 造测；负向历史片段单独展示无完整题包时的 AI 造测功能。
大数据版 v2 是 90 点，未将在线模型的已知错误候选作为成功案例。

## 题包与复现

从 [分片交付目录](../runs/releases/demo/README.md)还原后，上传 `problems/integer_decomposition/sqrt_problem.jsonl` 或 `problems/merge_set_problem.jsonl`。
外部题也可执行 `python scripts/make_integer_decomposition_demo.py` 重新生成，再以 `python scripts/verify_integer_decomposition_demo.py` 校准。
已有内部样例准备入口为 `scripts/prepare_demo_sample.py`；原始子集未入库时，直接使用交付包中的完整单题 JSONL。

题解和过程由 Reviewer 审查；AC/WA/TLE 只由判题器决定，两者组合为独立状态。
本片 16 个内部测试来自所保存的 LiveCodeBench 数据，不是 AtCoder 站外提交成绩。

## 部署说明（环境搭建）

### 1. 环境要求
- **操作系统**：Windows 10/11、macOS、Linux 均可（本项目开发机为 Windows，沙箱判题走 Docker 容器）
- **Python**：3.11（推荐 conda 隔离；Windows 上 `python` 常被 Microsoft Store 占位，请用 `conda activate hy3-oj` 或绝对路径）
- **Docker**：Docker Desktop（沙箱判题容器；Windows 需**手动启动** Docker Desktop，且不可用 rlimit，已用进程组整杀兜底）
- **网络**：可访问腾讯混元 Hy3 API 与 Docker Hub（拉镜像）

### 2. 获取代码
```bash
git clone https://github.com/vankari/hy3-oj
cd hy3-oj
```

### 3. 创建运行环境
```powershell
conda env create -f environment.yml
conda activate hy3-oj
pip install -e . --no-deps
# 备选：pip install -r requirements.txt（需 Python 3.11）
```

### 4. 配置密钥（零入库）
```powershell
cp .env.example .env      # 编辑 .env 填入 HY3_API_KEY=你的密钥
```
- 密钥**只**从环境变量 / `.env` 读取，代码、yaml、md、commit 均不含明文 key（任务书硬性要求）
- 若 D 盘已满、C 盘有空间：在 `.env` 设 `HY3_HF_CACHE=C:/hy3-oj-cache/hf` 把 HF 缓存切到 C 盘

### 5. 准备 Docker 镜像
```powershell
docker pull python:3.11-slim     # Python3 判题沙箱
docker pull gcc:13               # C++17 判题沙箱（g++ 13.4，用于硬题 TLE 攻坚）
```
> C++17 路径：`gcc:13` 镜像同时内置 `python3`（运行编译/执行 runner），无需自建镜像。

### 6. 启动演示（GUI）
```powershell
conda activate hy3-oj
python scripts/run_demo.py       # 自动打开 http://localhost:8501
```
界面为单一对话工作区：底部粘贴或上传题目，侧边栏查看历史对话。
- 结果含题解、代码、过程评估三个页签。
- 解题偏好、批量评测记录和人工反馈放在折叠区。

### 7. 批量评测（CLI，非 GUI）
```powershell
# 单题子集闭环（可强制语言，避免非算法 RE/TLE 干扰判断）
python scripts/run_solve.py --subset data/subsets/subset_mid100.jsonl `
    --out runs/closed_loop_mid100.jsonl --lang cpp --concurrency 2
# 正式集：解题 → 过程评估 → 分层报告（断点续跑）
python scripts/run_eval.py --subset data/subsets/subset_v1.jsonl `
    --out-solve runs/closed_loop_v3_300.jsonl --out-review runs/review_v3_300.jsonl `
    --report docs/formal_eval_report.md
```

### 8. Windows 专属注意事项
- **Docker 必须手动启动** Docker Desktop，否则判题直接失败
- **控制台 GBK 乱码**：各入口已 `sys.stdout.reconfigure(utf-8)`；涉及中文路径的操作优先用脚本文件执行
- **D 盘 100% 满**：HF 缓存经 `HY3_HF_CACHE` 切 C 盘；Docker 镜像存储也在 C 盘
- **`python` 占位**：始终 `conda activate hy3-oj` 或用绝对路径 `D:\ANACONDA\envs\hy3-oj\python.exe`

### 9. 故障排查
| 现象 | 原因 | 处理 |
|---|---|---|
| 页面打不开 / 解题报 key 错 | 未配置 HY3_API_KEY | 检查 `.env`（步骤 4） |
| 判题立刻失败 / 无容器 | Docker 未启动或镜像缺失 | 步骤 5 拉镜像并启动 Docker |
| C++ 题编译/执行异常 | 误用 python 镜像 | cpp 模式自动选 `gcc:13`，确认已 `pull` |
| API 超时 | 误走代理 | 运行前清空 `HTTP_PROXY`/`HTTPS_PROXY` 等环境变量 |
| 中文路径乱码 | PowerShell GBK | 用脚本文件执行（步骤 8） |
