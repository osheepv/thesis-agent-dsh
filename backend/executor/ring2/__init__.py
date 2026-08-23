# -*- coding: utf-8 -*-
"""环2 开题评审执行体（M2 二期：真实检索 + LLM 新颖度判定）。

职责：对候选题目做"学术查新"——检索真实文献判断"别人是否做过、有无空间"，
输出新颖度结论（HIGH/MEDIUM/LOW）+ 风险说明 + 与前人最大不同。

设计要点：
    1. 真实检索：用 LiteratureService.search 检索题目关键词，取回相似研究
       （严禁 LLM 编造"有人做过/没人做过"）。
    2. 相似度判定：对检索结果做标题相似度评分，计算"已有人做过"的逼近度。
    3. LLM 综合判定：注入候选题 + 相似研究清单（标题/作者/年/摘要），
       判定 HIGH/MEDIUM/LOW + "与前辈最大不同" + 风险。
    4. 空检索（0 命中）= 空白领域利好（HIGH + "本次未检索到相似研究，注意库覆盖"）。
    5. LOW → accept=False, fallbackTo=1（回退环1 换题/收敛）。
    6. 保留 HITL 标志（环2/4/8/10 网关环节），人工确认由 M1 confirm_hitl 承载。

注意：本环为 HITL 网关环节（hitl_required=True），执行体只产出评审结果，
人工确认动作与执行体解耦。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.lit import LiteratureService, get_lit_service
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring2")

#: 文献检索开关（与环3 一致）
_LIT_ENABLED = os.environ.get("THESIS_LIT_ENABLED", "true").lower() not in ("0", "false", "no")

#: 相似度阈值（≥ 判"高度相似"）
_HIGH_SIMILAR = 0.7


class SimilarWork(BaseModel):
    """检索到的相似研究。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="标题")
    authors: list[str] = Field(default_factory=list, description="作者")
    year: int | None = Field(default=None, description="年份")
    venue: str = Field(default="", description="期刊/会议")
    doi: str = Field(default="", description="DOI")
    similarity: float = Field(default=0.0, description="与候选题的相似度")
    note: str = Field(default="", description="备注（如'库覆盖有限'）")


class NoveltyResult(BaseModel):
    """环2 开题评审结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    topic: str = Field(default="", description="候选题目")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    novelty_level: str = Field(default="", description="HIGH/MEDIUM/LOW")
    similar_count: int = Field(default=0, description="相似研究数")
    similar_works: list[SimilarWork] = Field(default_factory=list, description="相似研究清单")
    differ_from_prior: str = Field(default="", description="与前人最大不同")
    risk_notes: list[str] = Field(default_factory=list, description="风险说明")
    recommendation: str = Field(default="", description="放行/回退建议")


class LLMNoveltyOut(BaseModel):
    """LLM 新颖度判定输出。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    novelty_level: str = Field(default="", description="HIGH/MEDIUM/LOW")
    differ_from_prior: str = Field(default="", description="与前人最大不同")
    risk_notes: list[str] = Field(default_factory=list, description="风险说明")
    recommendation: str = Field(default="", description="放行/回退建议")


def _title_similarity(a: str, b: str) -> float:
    """标题字符重叠率（0~1，粗略）。"""
    import re

    sa = re.sub(r"\W+", "", (a or "").lower())
    sb = re.sub(r"\W+", "", (b or "").lower())
    if not sa or not sb:
        return 0.0
    common = sum(1 for c in sa if c in sb)
    return common / max(len(sa), len(sb))


def _llm_judge(ctx: ExecContext, topic: str, similar: List[Dict[str, Any]]) -> LLMNoveltyOut:
    """LLM 判定新颖度。"""
    if not similar:
        sim_text = "（本次未检索到相似研究——可能空白领域，也可能数据库覆盖有限，请客观判断）"
    else:
        sim_text = "\n".join(
            f"- {s.get('title', '')} | {s.get('year', '')} | {s.get('venue', '')} | "
            f"相似度 {s.get('similarity', 0):.2f}"
            for s in similar
        )
    prompt = prompt_repo.render("ring2_review", {
        "topic": topic,
        "subject_field": ctx.subject_field,
        "degree_label": ctx.degree.label,
        "similar_text": sim_text,
    })
    return get_llm_client().generate_json(
        system=prompt["system"],
        prompt=prompt["prompt"],
        model_cls=LLMNoveltyOut,
    )


@register_executor
class Ring2DefenseReviewExecutor(RingExecutor):
    """环2 开题评审执行体（新颖度评估 + HITL 标志）。"""

    ring_type: RingType = RingType.RING_2
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        topic = (getattr(ctx, "theme", "") or "").strip() or (
            f"{(ctx.subject_field or '')}研究"
        )
        if not ctx.subject_field.strip():
            raise ValueError("subject_field 不能为空")

        similar: List[Dict[str, Any]] = []
        if _LIT_ENABLED:
            svc: LiteratureService = get_lit_service()
            try:
                hits = svc.search(topic, max_results=8)
                for h in hits:
                    sim = _title_similarity(topic, h.title)
                    similar.append(
                        {"title": h.title, "authors": h.authors, "year": h.year,
                         "venue": h.venue, "doi": h.doi, "similarity": round(sim, 3),
                         "note": "高度相似" if sim >= _HIGH_SIMILAR else ""}
                    )
                # 按相似度排序，取前 5
                similar.sort(key=lambda s: s["similarity"], reverse=True)
                similar = similar[:5]
            except Exception as exc:  # noqa: BLE001
                logger.warning("环2 检索相似研究失败: %s", exc)
        else:
            logger.info("环2 文献检索禁用（THESIS_LIT_ENABLED=false），跳过真实查新")

        # LLM 判定
        verdict = None
        source = "mock"
        settings = get_llm_settings()
        if settings.enabled and settings.api_key:
            try:
                verdict = _llm_judge(ctx, topic, similar)
                source = "deepseek"
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环2 LLM 判定不可用，回退规则：%s", exc)
                else:
                    raise

        if verdict is not None:
            level = (verdict.novelty_level or "MEDIUM").upper()
            differ = verdict.differ_from_prior
            risks = verdict.risk_notes
            rec = verdict.recommendation
        else:
            # 规则兜底：无检索命中 = 空白利好（HIGH）；相似度≥0.7 高度相似 = LOW
            high_sim = [s for s in similar if s["similarity"] >= _HIGH_SIMILAR]
            if not similar or not high_sim:
                level = "HIGH" if not similar else "MEDIUM"
                differ = (
                    "未检索到直接相似研究，需确认数据库覆盖后判断是否空白领域"
                    if not similar else
                    f"存在 {len(high_sim)} 条高度相似研究，但仍有差异化空间"
                )
                risks = ["检索覆盖有限，建议人工补充查新" if not similar else "相似研究较多，需强差异化"]
                rec = "建议放行，但人工复核查新覆盖"
            else:
                level = "LOW"
                differ = f"已有 {len(high_sim)} 条高度相似研究（如 {high_sim[0]['title'][:30]}），无明显差异化"
                risks = ["选题已被研究，回退环1 换题或收敛"]
                rec = "回退环1 重新选题"

        result = NoveltyResult(
            topic=topic,
            degree=ctx.degree,
            novelty_level=level,
            similar_count=len(similar),
            similar_works=[SimilarWork(**s) for s in similar],
            differ_from_prior=differ,
            risk_notes=risks,
            recommendation=rec,
        )

        accept = level != "LOW"
        issues = [] if accept else [f"新颖度 {level}，{rec}"]
        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=accept,
            fallbackTo=1 if not accept else None,  # LOW 回退环1 换题
            issues=issues,
            evidence={
                "novelty_level": level,
                "similar_count": len(similar),
                "similarity_max": max((s["similarity"] for s in similar), default=0.0),
                "source": source,
                "sources": ["crossref", "openalex"] if _LIT_ENABLED else [],
                "note": "真实检索支撑，未命中不编造；HITL 人工确认由 M1 承载",
            },
        )
