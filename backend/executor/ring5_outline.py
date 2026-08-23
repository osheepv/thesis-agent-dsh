# -*- coding: utf-8 -*-
"""环5 大纲生成执行体（M2 二期：LLM 优先 + Mock 回退）。

职责：根据选题（``ctx.theme``）生成章节结构蓝图（Outline：章/节/要点），
体现学位差异——本科章节少、博士章节深。

LLM 接入（决策 D1）：
    优先调用 DeepSeek（JSON 结构化输出）生成大纲；失败时按
    ``LLMSettings.fallback_to_mock`` 决定回退确定性 Mock 或抛错。
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.lit import lit_pool_block
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring5")


class OutlineNode(BaseModel):
    """大纲节点（章 / 节 / 要点）。

    用 level + number + title + points 统一表达多级结构。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    level: int = Field(default=1, description="层级：1 章、2 节、3 要点")
    number: str = Field(default="", description="编号，如 '第1章'/'1.1'/'1.1.1'")
    title: str = Field(default="", description="标题")
    points: list[str] = Field(default_factory=list, description="本节点要点描述")


class LLMOutlineOut(BaseModel):
    """LLM 环5 输出模型（要求严格按此 schema 返回 JSON）。"""

    theme: str = Field(default="", description="题目")
    degree: str = Field(default="", description="学位层次 BACHELOR/MASTER/PHD")
    chapters: list[OutlineNode] = Field(default_factory=list, description="章节节点（平铺，含 level 区分）")
    summary: str = Field(default="", description="大纲整体说明")


class OutlineResult(BaseModel):
    """环5 大纲执行体结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    theme: str = Field(default="", description="题目")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    chapters: list[OutlineNode] = Field(default_factory=list, description="章节树结构")
    summary: str = Field(default="", description="大纲整体说明")


#: 学位差异化的章节结构模板（本科章节少、博士章节深）。
_DEGREE_CHAPTERS: dict[Degree, list[dict]] = {
    Degree.BACHELOR: [
        {"n": "第1章", "title": "绪论", "size": 2,
         "points": ["研究背景与意义", "国内外研究现状简述", "研究内容与章节安排"]},
        {"n": "第2章", "title": "相关理论与技术基础", "size": 2,
         "points": ["领域理论基础", "关键技术/方法介绍"]},
        {"n": "第3章", "title": "系统设计与实现", "size": 3,
         "points": ["总体设计", "核心模块实现", "关键流程说明"]},
        {"n": "第4章", "title": "实验与结果分析", "size": 2,
         "points": ["实验设置与数据", "结果对比与分析", "讨论"]},
        {"n": "第5章", "title": "总结与展望", "size": 1,
         "points": ["工作总结", "不足与展望"]},
    ],
    Degree.MASTER: [
        {"n": "第1章", "title": "绪论", "size": 3,
         "points": ["研究背景与意义", "国内外研究现状述评", "研究内容、方法与创新点", "章节安排"]},
        {"n": "第2章", "title": "相关理论与方法综述", "size": 3,
         "points": ["基础理论", "相关方法比较", "方法选型依据"]},
        {"n": "第3章", "title": "模型/方法设计与形式化", "size": 4,
         "points": ["问题定义与建模", "算法/模型设计", "理论性质分析", "复杂度与可行性讨论"]},
        {"n": "第4章", "title": "系统实现", "size": 3,
         "points": ["总体架构", "核心模块详细设计", "边界与异常处理"]},
        {"n": "第5章", "title": "实验设计与结果分析", "size": 4,
         "points": ["实验设置与评估指标", "基准对比", "消融实验", "分析与讨论"]},
        {"n": "第6章", "title": "总结与展望", "size": 2,
         "points": ["工作总结", "研究局限", "未来展望"]},
    ],
    Degree.PHD: [
        {"n": "第1章", "title": "绪论", "size": 4,
         "points": ["研究背景与问题界定", "研究现状与文献综述", "科学问题与研究目标", "研究思路与技术路线", "创新点与章节安排"]},
        {"n": "第2章", "title": "理论基础与文献综述", "size": 4,
         "points": ["理论基础与形式化框架", "国内外研究系统梳理", "现有方法的不足与挑战", "本研究定位"]},
        {"n": "第3章", "title": "核心理论/方法与建模", "size": 5,
         "points": ["问题建模与假设", "方法/模型构建", "理论性质证明与分析", "算法设计与伪代码", "与已有方法对比分析"]},
        {"n": "第4章", "title": "方法改进与扩展研究", "size": 5,
         "points": ["改进策略", "扩展性分析", "泛化与鲁棒性讨论", "边界条件与局限性"]},
        {"n": "第5章", "title": "实验验证与评估", "size": 4,
         "points": ["数据集与实验设置", "评估体系与指标", "多组对比实验", "消融与敏感性分析"]},
        {"n": "第6章", "title": "结论与展望", "size": 3,
         "points": ["研究结论", "理论/实践贡献", "研究不足", "未来工作方向"]},
        {"n": "第7章", "title": "总结与后续计划", "size": 2,
         "points": ["整体总结", "后续研究计划"]},
    ],
}


def _llm_generate(ctx: ExecContext) -> OutlineResult:
    """调用 DeepSeek 生成大纲（LLM 分支，失败抛异常由调用方决定回退）。"""
    degree_gen = {
        Degree.BACHELOR: "本科：5 章（绪论/理论/设计/实验/总结），章下 2~3 节",
        Degree.MASTER: "硕士：6 章（绪论/综述/方法/实现/实验/总结），章下 3~4 节",
        Degree.PHD: "博士：7 章（绪论/综述/方法/扩展/实验/结论/计划），章下 4~5 节",
    }[ctx.degree]
    tpl = prompt_repo.render("ring5_outline", {
        "theme": ctx.theme,
        "subject_field": ctx.subject_field,
        "degree_label": ctx.degree.label,
        "degree_gen": degree_gen,
        "literature_block": lit_pool_block(
            [it if isinstance(it, dict) else it.to_dict() for it in ctx.literature]
            if ctx.literature else []
        ),
        "argument_map_block": (
            "【已批准论证图】\n"
            + json.dumps(getattr(ctx, "argument_map", {}), ensure_ascii=False)
            if getattr(ctx, "argument_map", {})
            else "【论证图】本任务尚未启用结构化论证图。"
        ),
        "research_protocol_block": (
            "【已批准研究协议】\n"
            + json.dumps(getattr(ctx, "research_protocol", {}), ensure_ascii=False)
            if getattr(ctx, "research_protocol", {})
            else "【研究协议】本任务尚未启用结构化研究协议。"
        ),
    })
    raw = get_llm_client().generate_json(
        system=tpl["system"],
        prompt=tpl["prompt"],
        model_cls=LLMOutlineOut,
    )
    return OutlineResult(
        theme=raw.theme or ctx.theme,
        degree=ctx.degree,
        chapters=raw.chapters,
        summary=raw.summary,
    )


@register_executor
class Ring5OutlineExecutor(RingExecutor):
    """环5 大纲生成执行体。"""

    ring_type: RingType = RingType.RING_5
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        theme = ctx.theme.strip() or f"基于{ctx.subject_field}的研究"

        # LLM 优先；失败按配置回退 Mock 或报错
        source = "mock"
        settings = get_llm_settings()
        outline_result = None
        if settings.enabled and settings.api_key:
            try:
                outline_result = _llm_generate(ctx)
                source = "deepseek"
                if not outline_result.chapters:
                    raise StructuredOutputError("LLM 返回空大纲")
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环5 LLM 不可用，回退 Mock：%s", exc)
                    return self._fallback_mock(ctx, theme)
                raise

        if outline_result is None:
            if not settings.fallback_to_mock:
                raise LLMError("环5需要可用的 LLM；正式模式禁止静默回退 Mock")
            return self._fallback_mock(ctx, theme)

        evidence = {
            "degree": ctx.degree.value,
            "chapter_count": len(outline_result.chapters),
            "node_count": sum(1 for c in outline_result.chapters if c.level >= 2),
            "source": source,
        }

        return ExecResult(
            output=outline_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )

    def _fallback_mock(self, ctx: ExecContext, theme: str) -> ExecResult:
        """LLM 返回空时兜底：确定性 Mock 大纲。"""
        chapters_spec = _DEGREE_CHAPTERS[ctx.degree]

        chapters: list[OutlineNode] = []
        for spec in chapters_spec:
            sections: list[OutlineNode] = []
            points = spec["points"]
            sec_titles = points if len(points) <= 6 else points[:6]
            for i, sec in enumerate(sec_titles, start=1):
                number = f"{spec['n'].replace('第', '').replace('章', '')}.{i}"
                sections.append(
                    OutlineNode(
                        level=2,
                        number=number,
                        title=sec,
                        points=[f"深入展开：{sec} 相关论述与数据/案例支撑。"],
                    )
                )
            chapters.append(
                OutlineNode(
                    level=1,
                    number=spec["n"],
                    title=spec["title"],
                    points=[f"{spec['title']}下共 {len(sections)} 节，层次深度匹配{ctx.degree.label}要求。"],
                )
            )
            chapters.extend(sections)

        outline_result = OutlineResult(
            theme=theme,
            degree=ctx.degree,
            chapters=chapters,
            summary=(
                f"共 {len(chapters_spec)} 章；已按{ctx.degree.label}层次生成"
                f"{len(chapters)} 个章节/节节点（本科章节少、博士章节深）。"
            ),
        )
        return ExecResult(
            output=outline_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence={"degree": ctx.degree.value, "source": "mock"},
        )
