# -*- coding: utf-8 -*-
"""环1 选题执行体（M2 一期，确定性 Mock）。

职责：根据 :class:`ExecContext` 的 ``subject_field + degree`` 生成候选题目列表，
并为每道题给出创新点定位与可行性评估。

DSH 二期接入点：
    真实实现应调用 DSH（LLM 检索+生成）根据知识库与文献库生成候选题目与创新点。
    本期以规则/模板占位，保证闭环可运行。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)


class TopicCandidate(BaseModel):
    """单条选题候选。

    Attributes:
        title: 题目。
        innovation: 创新点定位。
        feasibility: 可行性评估（数据可得性/工作量/研究条件）。
        degree_fit: 与该学位层次的匹配度（用于体现学位差异）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="题目")
    innovation: str = Field(default="", description="创新点定位")
    feasibility: str = Field(default="", description="可行性评估")
    degree_fit: str = Field(default="", description="与该学位层次的匹配度")


class TopicResult(BaseModel):
    """环1 选题执行体的结构化产物（放入 ExecResult.output 之前的可序列化载体）。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    subject_field: str = Field(default="", description="学科/专业方向")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    candidates: list[TopicCandidate] = Field(default_factory=list, description="候选题目列表")
    recommendation: str = Field(default="", description="综合推荐理由")


#: 学位差异化策略参数（本科浅、硕士中、博士深）。
_STRATEGY: dict[Degree, dict[str, int | str]] = {
    Degree.BACHELOR: {
        "count": 3,
        "depth": "应用型，立足已有理论与方法做具体场景落地，创新点聚焦'场景适配'。",
        "expected_words": 10000,
    },
    Degree.MASTER: {
        "count": 4,
        "depth": "研究型，在现有理论基础上做增量改进，创新点聚焦'模型/方法改进'。",
        "expected_words": 30000,
    },
    Degree.PHD: {
        "count": 5,
        "depth": "前沿深究型，提出新框架/新方法或突破既有范式，创新点聚焦'理论贡献'。",
        "expected_words": 60000,
    },
}

#: 默认创新方向词库（Mock 占位，DSH 接入后由 LLM 替换）。
_INNOVATION_THEMES: list[str] = [
    "基于多模态数据融合",
    "面向真实场景约束",
    "融合领域先验知识驱动",
    "低成本高鲁棒",
    "自适应可解释",
    "面向长尾小样本场景",
]


def _build_candidate(idx: int, subject_field: str, degree: Degree, strategy: dict) -> TopicCandidate:
    """按模板生成单条候选（确定性，无随机）。"""
    theme = _INNOVATION_THEMES[idx % len(_INNOVATION_THEMES)]
    title = f"{theme.strip('，')}{subject_field} 的自动识别与关键要素分析研究"
    degree_label = degree.label
    innovation = (
        f"（{idx + 1}）{strategy['depth']} 结合领域知识构建 {subject_field} 专用"
        f"评估指标体系，实现端到端自动化建模。"
    )
    feasibility = (
        f"现有公开数据集与文献充足，工作量与{degree_label}培养要求匹配，"
        f"研究可行性高。"
    )
    degree_fit = f"匹配{degree_label}层次，正文预计 {strategy['expected_words']} 字量级。"
    return TopicCandidate(
        title=title,
        innovation=innovation,
        feasibility=feasibility,
        degree_fit=degree_fit,
    )


@register_executor
class Ring1TopicExecutor(RingExecutor):
    """环1 选题执行体。

    输入：subject_field + degree。
    输出：候选题目列表 + 创新点定位 + 可行性评估（确定性 Mock）。
    """

    ring_type: RingType = RingType.RING_1
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        if not ctx.subject_field.strip():
            raise ValueError("subject_field 不能为空")
        strategy = _STRATEGY[ctx.degree]
        count = int(strategy["count"])
        candidates = [_build_candidate(i, ctx.subject_field, ctx.degree, strategy) for i in range(count)]

        # 综合推荐：默认推荐首条（确定性）。
        recommendation = (
            f"综合创新度、可行性与{ctx.degree.label}层次匹配度，推荐首选：\n"
            f"「{candidates[0].title}」\n"
            f"推荐理由：{candidates[0].feasibility}"
        )

        topic_result = TopicResult(
            subject_field=ctx.subject_field,
            degree=ctx.degree,
            candidates=candidates,
            recommendation=recommendation,
        )

        # DSH 二期接入点：此处应调用 DSH 生成带真实引用来源的 evidence。
        evidence = {
            "strategy": strategy["depth"],
            "candidate_count": len(candidates),
            "source_mock": "确定性 Mock（DSH 二期接入）",
            "degree": ctx.degree.value,
        }

        return ExecResult(
            output=topic_result.model_dump_json(indent=2, ensure_ascii=False),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )
