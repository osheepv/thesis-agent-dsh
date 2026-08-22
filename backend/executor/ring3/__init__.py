# -*- coding: utf-8 -*-
"""环3 文献调研执行体（M2 二期：真实检索，决策 D2）。

职责：根据选题（``ctx.theme`` / ``ctx.subject_field``）系统搜集文献，
构建证据池（题录 + 摘要 + 分类 + 可靠度 + GB/T 7714 导出）。

设计要点：
    1. 检索走真实 API（Crossref + OpenAlex，common.lit.LiteratureService），
       严禁 LLM 编造文献（学术诚信红线）。
    2. 学位分级目标数量：本科 ~30 / 硕士 50~80 / 博士 100+；
       免费 API 示例取 top N（26 条以内），完整规模标注"需订阅源补全"。
    3. 中文条目自动标记 reliability=uncertain，提示"待人工/订阅源复核"。
    4. LLM 仅用于"检索词扩展 + 摘要压缩"，不作为文献来源。
"""
from __future__ import annotations

import json
import logging
import os
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.citation import format_gbt7714
from common.lit import LiteratureService, LitItem, get_lit_service
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring3")

#: 环境开关：false 时环3/环8 跳过真实检索（离线/测试），默认 true
_LIT_ENABLED = os.environ.get("THESIS_LIT_ENABLED", "true").lower() not in ("0", "false", "no")

#: 学位分级目标文献数（免费 API 单次演示检索的上限）
_DEGREE_TARGETS: dict[Degree, int] = {
    Degree.BACHELOR: 30,
    Degree.MASTER: 80,
    Degree.PHD: 100,
}
#: 每次真实检索最多取数（API 限流友好）
_API_FETCH_LIMIT = 24

#: 文献分类关键词（按标题匹配，用于证据池归档）
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("综述", ["survey", "review", "综述", "进展", "回顾", "overview"]),
    ("理论", ["theory", "framework", "model", "理论", "框架", "模型", "形式化"]),
    ("方法", ["method", "algorithm", "approach", "方法", "算法", "网络", "架构"]),
    ("实证", ["experiment", "empirical", "dataset", "实验", "实证", "数据集", "评估"]),
]


class LiteratureItem(BaseModel):
    """证据池单条文献。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="题名")
    authors: list[str] = Field(default_factory=list, description="作者")
    year: int | None = Field(default=None, description="年份")
    venue: str = Field(default="", description="期刊/会议")
    doi: str = Field(default="", description="DOI")
    abstract: str = Field(default="", description="摘要")
    citation_count: int | None = Field(default=None, description="被引次数")
    category: str = Field(default="", description="分类：综述/理论/方法/实证")
    reliability: str = Field(default="uncertain", description="可靠度 verified/matched/uncertain")
    gbt7714: str = Field(default="", description="GB/T 7714 引用")
    urls: list[str] = Field(default_factory=list, description="链接")


class LiteraturePoolResult(BaseModel):
    """环3 文献调研结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    theme: str = Field(default="", description="题目")
    subject_field: str = Field(default="", description="学科方向")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    items: list[LiteratureItem] = Field(default_factory=list, description="证据池文献清单")
    total: int = Field(default=0, description="总条目数")
    target_count: int = Field(default=0, description="学位目标数量")
    summary: str = Field(default="", description="调研说明（数据来源/可靠度/补全建议）")


def _categorize(title: str) -> str:
    """按标题关键词规则分类。"""
    low = (title or "").lower()
    for cat, kws in _CATEGORY_RULES:
        if any(k in low for k in kws):
            return cat
    return "方法"


def _llm_expand_queries(subject_field: str, theme: str) -> list[str]:
    """LLM 扩展检索词（可选；失败回退基础检索词）。"""
    settings = get_llm_settings()
    if not (settings.enabled and settings.api_key):
        return []
    from pydantic import BaseModel as BM

    class QueryOut(BM):
        queries: list[str]

    try:
        out = get_llm_client().generate_json(
            system="你是文献检索策略专家。",
            prompt=(
                f"【任务】围绕学科「{subject_field}」与题目「{theme}」生成 3 组文献检索词"
                "（中英文各一组，含核心方法与近义词），用于学术数据库检索。\n"
                "【格式】严格输出 JSON（含 \"json\" 键）：{\"queries\": [\"中文检索词\", \"English query\", \"关键词1 关键词2\"]}\n"
                "只输出 JSON。"
            ),
            model_cls=QueryOut,
            temperature=0.3,
        )
        return [q for q in out.queries if q.strip()][:3]
    except (LLMError, StructuredOutputError) as exc:
        logger.info("环3 LLM 检索词扩展不可用（%s），用基础检索词", exc)
        return []


def _to_lit_item(it: LitItem) -> LiteratureItem:
    """LitItem → LiteratureItem（分类 + GB/T 7714）。"""
    d = it.to_dict()
    return LiteratureItem(
        title=d["title"],
        authors=d["authors"],
        year=d["year"],
        venue=d["venue"],
        doi=d["doi"],
        abstract=d["abstract"][:300],
        citation_count=d["citation_count"],
        category=_categorize(d["title"]),
        reliability=d["reliability"],
        gbt7714=format_gbt7714(d),
        urls=d["urls"],
    )


@register_executor
class Ring3LiteratureReviewExecutor(RingExecutor):
    """环3 文献调研执行体。

    输入：theme（当前题目）+ subject_field + degree。
    输出：证据池（文献清单 + 分类 + GB/T 7714 + 可靠度标记）。
    """

    ring_type: RingType = RingType.RING_3
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        theme = (getattr(ctx, "theme", "") or "").strip() or f"基于{ctx.subject_field}的研究"
        if not ctx.subject_field.strip():
            raise ValueError("subject_field 不能为空")

        svc: LiteratureService = get_lit_service()
        queries = _llm_expand_queries(ctx.subject_field, theme)
        if not queries:
            queries = [theme, ctx.subject_field, f"{ctx.subject_field} {theme}"]

        # 环境开关：离线/测试直接返回空池（不阻塞闭环）
        if not _LIT_ENABLED:
            result = LiteraturePoolResult(
                theme=theme, subject_field=ctx.subject_field, degree=ctx.degree,
                items=[], total=0, target_count=_DEGREE_TARGETS[ctx.degree],
                summary="文献检索已禁用（THESIS_LIT_ENABLED=false），池为空；环5/6 须禁止引用。",
            )
            return ExecResult(
                output=result.model_dump_json(indent=2),
                accept=True, fallbackTo=None, issues=["文献检索禁用，池空"],
                evidence={"sources": [], "fetched": 0, "note": "THESIS_LIT_ENABLED=false"},
            )

        # 逐检索词真实检索（去重合并）
        seen_doi: set[str] = set()
        items: List[LiteratureItem] = []
        for q in queries[:3]:
            try:
                hits = svc.search(q, max_results=_API_FETCH_LIMIT)
            except Exception as exc:  # noqa: BLE001
                logger.warning("检索词 %s 失败: %s", q, exc)
                continue
            for h in hits:
                key = h.doi.strip().lower() if h.doi else h.title.strip().lower()
                if key in seen_doi:
                    continue
                seen_doi.add(key)
                items.append(_to_lit_item(h))
                if len(items) >= _API_FETCH_LIMIT:
                    break

        target = _DEGREE_TARGETS[ctx.degree]
        # 可靠度统计
        verified = sum(1 for it in items if it.reliability in ("verified", "matched"))
        uncertain_cn = sum(1 for it in items if it.reliability == "uncertain")
        summary = (
            f"共检索 {len(items)} 条（真实 API：Crossref + OpenAlex）；"
            f"可靠命中 {verified} 条；中文/低置信 {uncertain_cn} 条需人工复核。"
            f"学位目标 {target} 条——免费 API 单次演示取 top {_API_FETCH_LIMIT} 条，"
            f"完整规模需订阅源（NCPSSD/知网/万方）或人工补全。"
        )

        result = LiteraturePoolResult(
            theme=theme,
            subject_field=ctx.subject_field,
            degree=ctx.degree,
            items=items,
            total=len(items),
            target_count=target,
            summary=summary,
        )

        evidence = {
            "sources": ["crossref", "openalex"],
            "fetched": len(items),
            "target": target,
            "reliability": {"verified": verified, "uncertain": uncertain_cn},
            "note": "文献来源真实 API，严禁编造；中文条目待人工复核",
        }

        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[] if verified > 0 else ["未命中任何可靠文献，请调整检索词或人工建池"],
            evidence=evidence,
        )
