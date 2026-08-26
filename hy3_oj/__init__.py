"""Hy3-OJ：基于腾讯混元 Hy3 的算法竞赛智能解题与过程评估系统。

模块地图（详见 docs/项目架构设计.md）：
- core    编排内核：数据契约(schemas) + 闭环状态机(pipeline) + 配置(config)
- llm     模型接入层：Hy3 API 封装(client) + 快慢思考调度(router) + 成本计量(pricing)
- agents  六个智能体：parser/planner/coder/tester/reflector/reviewer
- sandbox 执行判题：docker_executor/judge/cube_adapter
- data    数据层：CodeContests(优先)/LiveCodeBench(后置) 加载与子集抽样
- eval    评测层：runner/metrics/process_eval/report
- prompts 提示资产（yaml，版本化管理）
- ui      Streamlit 交互 Demo（后置）
"""

__version__ = "0.1.0"
