# -*- coding: utf-8 -*-
"""环4 综述评审执行体（M2 二期：文献池竞争度 + 创新点包住检查）。

职责：输入环3 文献池 + 选题，判断"综述是否暴露创新点已有人做"——
    池内竞争度（与选题标题相似度 > 阈值 的条目数）+ 创新点被包住风险
    → LLM 评审结论 + 回退目标（环2 重评估 / 环3 补文献）。

设计要点：
    1. 池内竞争度：对文献池条目做标题相似度评分，>0.6 视为"直接相关"，
       >0.8 视为"高度重叠"（创新点可能被包住）。
    2. LLM 评审：注入池内直接相关文献 + 选题，判定"综述是否立得住"、
       "创新点是否与已有工作重复"、给出"回退哪里"建议。
    3. 空池/禁用：标记"需人工补池"，不判 LOW（避免误伤），HITL 人工把关。
    4. 保留 HITL 标志（环4 网关环节），人工确认由 M1 confirm_hitl 承载。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring4")

#: 池内"直接相关"相似度阈值
_RELEVANT_SIM = 0.6
#: 池内"高度重叠"相似度阈值（创新点被包住风险）
_OVERLAP_SIM = 0.8


class PoolHit(BaseModel):
    """池内与选题直接相关的条目。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="标题")
    authors: list[str] = Field(default_factory=list, description="作者")
    year: int | None = Field(default=None, description="年份")
    venue: str = Field(default="", description="期刊/会议")
    similarity: float = Field(default=0.0, description="与选题相似度")
    overlap: bool = Field(default=False, description="是否高度重叠")


class ReviewResult(BaseModel):
    """环4 综述评审结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    topic: str = Field(default="", description="选题")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    pool_count: int = Field(default=0, description="文献池条数")
    relevant_count: int = Field(default=0, description="直接相关条数")
    overlap_count: int = Field(default=0, description="高度重叠条数")
    relevant_hits: list[PoolHit] = Field(default_factory=list, description="直接相关清单")
    verdict: str = Field(default="", description="评审结论（顺/需补充/需重评估）")
    risks: list[str] = Field(default_factory=list, description="风险")
    recommendation: str = Field(default="", description="建议")


class LLMReviewOut(BaseModel):
    """LLM 综述评审输出。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    verdict: str = Field(default="", description="顺/需补充/需重评估")
    risks: list[str] = Field(default_factory=list, description="风险")
    recommendation: str = Field(default="", description="建议")


def _title_similarity(a: str, b: str) -> float:
    sa = re.sub(r"\W+", "", (a or "").lower())
    sb = re.sub(r"\W+", "", (b or "").lower())
    if not sa or not sb:
        return 0.0
    common = sum(1 for c in sa if c in sb)
    return common / max(len(sa), len(sb))


@register_executor
class Ring4ReviewExecutor(RingExecutor):
    """环4 综述评审执行体（创新点包住检查 + HITL 标志）。"""

    ring_type: RingType = RingType.RING_4
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        topic = (getattr(ctx, "theme", "") or "").strip() or f"{(ctx.subject_field or '')}研究"
        pool = ctx.literature or []

        # 池内竞争度计算
        hits: List[Dict[str, Any]] = []
        for it in pool:
            title = it.get("title", "") if isinstance(it, dict) else getattr(it, "title", "")
            if not title:
                continue
            sim = _title_similarity(topic, title)
            if sim >= _RELEVANT_SIM:
                hits.append(
                    {"title": title, "authors": it.get("authors", []) if isinstance(it, dict) else [],
                     "year": it.get("year") if isinstance(it, dict) else None,
                     "venue": it.get("venue", "") if isinstance(it, dict) else "",
                     "similarity": round(sim, 3),
                     "overlap": sim >= _OVERLAP_SIM}
                )
        hits.sort(key=lambda s: s["similarity"], reverse=True)
        overlap_count = sum(1 for h in hits if h["overlap"])

        # LLM 评审
        verdict = None
        source = "mock"
        settings = get_llm_settings()
        if settings.enabled and settings.api_key:
            try:
                verdict = self._llm_review(ctx, topic, hits, pool)
                source = "deepseek"
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环4 LLM 评审不可用，回退规则：%s", exc)
                else:
                    raise
        elif not settings.fallback_to_mock:
            raise LLMError("环4需要可用的 LLM；正式模式禁止静默回退规则判定")

        if verdict is not None:
            v = verdict.verdict
            risks = verdict.risks
            rec = verdict.recommendation
        else:
            # 规则兜底
            if not pool:
                v = "需补充"
                risks = ["文献池为空，综述无法立论，请先跑环3 检索补池"]
                rec = "回退环3 补文献"
            elif overlap_count >= 2:
                v = "需重评估"
                risks = [f"池内 {overlap_count} 条与选题高度重叠，创新点可能被包住"]
                rec = "回退环2 重新评估新颖度"
            elif overlap_count >= 1:
                v = "需补充"
                risks = [f"{overlap_count} 条高度重叠，建议加强差异化论述"]
                rec = "补充差异化论证后放行"
            else:
                v = "顺"
                risks = []
                rec = "综述可立论，放行至大纲"

        result = ReviewResult(
            topic=topic,
            degree=ctx.degree,
            pool_count=len(pool),
            relevant_count=len(hits),
            overlap_count=overlap_count,
            relevant_hits=[PoolHit(**h) for h in hits],
            verdict=v,
            risks=risks,
            recommendation=rec,
        )

        # 判定：需重评估 → 回退环2（不放行）；需补充 → 回退环3（不放行，池空/重叠须补）；顺 → 放行
        accept = v == "顺"
        fallback = 2 if v == "需重评估" else (3 if v == "需补充" else None)
        issues = [] if accept else [f"需处理：{rec}"]
        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=accept,
            fallbackTo=fallback,
            issues=issues,
            evidence={
                "pool_count": len(pool),
                "relevant_count": len(hits),
                "overlap_count": overlap_count,
                "source": source,
                "note": "池内竞争度 + LLM 评审；HITL 人工确认由 M1 承载",
            },
        )

    def _llm_review(self, ctx: ExecContext, topic: str, hits: List[Dict[str, Any]],
                    pool: List[Any]) -> LLMReviewOut:
        """LLM 综述评审。"""
        if not hits:
            hit_text = "（池内无直接相关条目）"
        else:
            hit_text = "\n".join(
                f"- {h['title']} | {h['year']} | {h['similarity']:.2f} | "
                f"{'高度重叠' if h['overlap'] else '直接相关'}"
                for h in hits
            )
        pool_text = f"池共 {len(pool)} 条（直接相关 {len(hits)} 条）"
        tpl = prompt_repo.render("ring4_review", {
            "topic": topic,
            "degree_label": ctx.degree.label,
            "pool_text": pool_text,
            "hit_text": hit_text,
        })
        return get_llm_client().generate_json(
            system=tpl["system"],
            prompt=tpl["prompt"],
            model_cls=LLMReviewOut,
        )
