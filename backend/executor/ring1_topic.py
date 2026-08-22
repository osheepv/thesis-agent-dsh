# -*- coding: utf-8 -*-
"""环1 选题执行体（M2 二期：LLM 优先 + Mock 回退）。

职责：根据 :class:`ExecContext` 的 ``subject_field + degree`` 生成候选题目列表，
并为每道题给出创新点定位与可行性评估。

LLM 接入（决策 D1）：
    优先调用 DeepSeek（common.llm.LLMClient，JSON 结构化输出）生成候选题目；
    未配置 key / 调用失败时，如 `LLMSettings.fallback_to_mock` 为 true 则回退
    到确定性 Mock（模板/规则生成，保证闭环可运行），否则抛 LLMError。
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring1")


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


class LLMTopicOut(BaseModel):
    """LLM 环1 输出模型（要求严格按此 schema 返回 JSON）。"""

    subject_field: str = Field(default="", description="学科/专业方向")
    degree: str = Field(default="", description="学位层次 BACHELOR/MASTER/PHD")
    candidates: list[TopicCandidate] = Field(default_factory=list, description="候选题目列表（3~5 条）")
    recommendation: str = Field(default="", description="综合推荐理由")


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


def _llm_generate(ctx: ExecContext) -> TopicResult:
    """调用 DeepSeek 生成候选题目（LLM 分支，失败抛 LLMError 由调用方决定回退）。"""
    degree_hint = {
        Degree.BACHELOR: "本科：应用型，创新点在'场景适配'，候选 3 条，每条 200 字内",
        Degree.MASTER: "硕士：研究型，创新点在'模型/方法改进'，候选 4 条，每条 250 字内",
        Degree.PHD: "博士：前沿深究型，创新点在'理论贡献/新框架'，候选 5 条，每条 300 字内",
    }[ctx.degree]
    prompt = (
        f"【任务】为学位论文选题生成候选题目。学科方向：{ctx.subject_field}；"
        f"学位层次：{ctx.degree.label}。{degree_hint}。\n"
        "【要求】每道题必须包含：title（题目）、innovation（创新点定位，说明与已有研究的不同）、"
        "feasibility（可行性评估：数据可得性、工作量、研究条件）、degree_fit（与该学位层次匹配度）；"
        "recommendation（综合推荐理由）。\n"
        "【输出格式】严格输出 JSON（包含 \"json\" 键），结构如下：\n"
        '{"subject_field": "…", "degree": "MASTER", '
        '"candidates": [{"title": "…", "innovation": "…", "feasibility": "…", "degree_fit": "…"}], '
        '"recommendation": "…"}\n'
        "只输出 JSON，不要有任何额外文字。"
    )
    raw = get_llm_client().generate_json(
        system="你是学术论文选题专家，熟悉本硕博培养目标差异。",
        prompt=prompt,
        model_cls=LLMTopicOut,
    )
    return TopicResult(
        subject_field=raw.subject_field or ctx.subject_field,
        degree=ctx.degree,
        candidates=raw.candidates,
        recommendation=raw.recommendation,
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

        # LLM 优先：调用 DeepSeek 生成候选题目；按配置决定失败时回退 Mock 或报错
        llm_result = None
        settings = get_llm_settings()
        if settings.enabled and settings.api_key:
            try:
                llm_result = _llm_generate(ctx)
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环1 LLM 不可用，回退 Mock：%s", exc)
                    llm_result = None
                else:
                    raise

        if llm_result is not None:
            topic_result = llm_result
            source = "deepseek"
        else:
            # 确定性 Mock 回退
            strategy = _STRATEGY[ctx.degree]
            count = int(strategy["count"])
            candidates = [_build_candidate(i, ctx.subject_field, ctx.degree, strategy) for i in range(count)]
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
            source = "mock"

        if len(topic_result.candidates) < 1:
            raise ValueError("选题生成失败：无候选题目")

        evidence = {
            "strategy": _STRATEGY[ctx.degree]["depth"],
            "candidate_count": len(topic_result.candidates),
            "source": source,
            "degree": ctx.degree.value,
        }

        return ExecResult(
            output=topic_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )
