"""全系统唯一数据契约（pydantic v2）。

设计原则：模块之间只传递本文件定义的模型，杜绝字符串拼接口；
所有模型带 schema 版本号，保证 runs/ 轨迹可回放、可复现。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1"


class Source(str, Enum):
    CODECONTESTS = "codecontests"
    LIVECODEBENCH = "livecodebench"


class Language(str, Enum):
    PYTHON3 = "python3"
    CPP17 = "cpp17"  # stretch goal


class GenMode(str, Enum):
    FAST = "fast"  # Hy3 快思考
    SLOW = "slow"  # Hy3 慢思考


class Verdict(str, Enum):
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    RE = "RE"
    CE = "CE"


class ProcessErrorType(str, Enum):
    """过程层错误分类（任务书 R5），与结果层 Verdict 交叉统计。"""

    MISREAD = "题意误读"
    CONCEPT = "概念理解错误"
    ALGO_CHOICE = "算法选型错误"
    COMPLEXITY = "复杂度误判"
    EDGE_CASE = "边界遗漏"
    IMPL = "实现逻辑错误"
    FORMAT = "格式不符"
    HALLUCINATION = "幻觉引用"


class ReviewStep(str, Enum):
    """五段式过程审查步骤（任务书 R4 错误步骤定位的粒度）。"""

    COMPREHENSION = "题意理解"
    ALGO_SELECTION = "算法选型"
    COMPLEXITY_PROOF = "复杂度论证"
    EDGE_HANDLING = "边界处理"
    IMPL_CONSISTENCY = "实现一致性"


class TestCase(BaseModel):
    __test__ = False  # 避免被 pytest 误收集

    version: str = SCHEMA_VERSION
    input: str
    expected_output: Optional[str] = None  # AI 生成用例可能无标答（靠对拍）
    is_ai_generated: bool = False
    validator_ref: Optional[str] = None


class Problem(BaseModel):
    version: str = SCHEMA_VERSION
    id: str
    source: Source
    statement: str
    constraints: str = ""
    samples: list[TestCase] = Field(default_factory=list)
    difficulty: Optional[str] = None  # easy/medium/hard（分层依据见 R2）
    tags: list[str] = Field(default_factory=list)
    public_tests: list[TestCase] = Field(default_factory=list)
    private_tests: list[TestCase] = Field(default_factory=list)
    generated_tests: list[TestCase] = Field(default_factory=list)
    reference_solutions: list[str] = Field(default_factory=list)  # 官方参考解（bug 注入验证用）


class Plan(BaseModel):
    version: str = SCHEMA_VERSION
    algorithm_tags: list[str] = Field(default_factory=list)
    approach: list[str] = Field(default_factory=list)  # 要点化解法（AlphaCodium 两阶段）
    time_complexity: str = ""
    space_complexity: str = ""
    edge_cases: list[str] = Field(default_factory=list)
    pseudocode: Optional[str] = None


class Solution(BaseModel):
    version: str = SCHEMA_VERSION
    code: str
    language: Language = Language.PYTHON3
    plan_ref: Optional[str] = None
    temperature: float = 0.2
    gen_mode: GenMode = GenMode.FAST


class JudgeResult(BaseModel):
    version: str = SCHEMA_VERSION
    verdict: Verdict
    failed_test: Optional[TestCase] = None
    stderr: str = ""
    time_ms: int = 0
    memory_kb: int = 0
    diff_excerpt: str = ""  # 首个失败点的输出差异摘要（供 reflector）


class Reflection(BaseModel):
    version: str = SCHEMA_VERSION
    cause_class: Verdict  # 结果层归因
    diagnosis: str = ""
    fix_instruction: str = ""
    counter_example: Optional[TestCase] = None  # WA 时强制先构造反例
    round_idx: int = 0


class StepVerdict(BaseModel):
    step: ReviewStep
    passed: bool
    evidence: str = ""  # 引用轨迹中的原文证据


class ProcessReview(BaseModel):
    """过程评估结论（任务书 R3/R4/R5/R6）。"""

    version: str = SCHEMA_VERSION
    step_verdicts: list[StepVerdict] = Field(default_factory=list)
    error_step: Optional[ReviewStep] = None  # 首个 fail 段
    error_type: Optional[ProcessErrorType] = None
    lucky_pass_flags: list[str] = Field(default_factory=list)  # 蒙对检测命中项
    process_score: float = 0.0  # 0~1 过程正确性得分
