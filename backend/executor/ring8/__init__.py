# -*- coding: utf-8 -*-
"""环8 引用校验执行体（M2 二期：多源交叉，决策 D2/D5）。

职责：输入参考文献题录（来自论文正文引用 + 参考文献列表），逐条核验真伪，
并输出 GB/T 7714 规范化结果；命中真实数据库的标 verified/matched，
未命中的（尤其中文）标"待人工复核"，杜绝伪引。

设计要点（对齐 refchecker 架构）：
    1. 多源交叉：Crossref DOI 反查（权威）+ OpenAlex 标题/作者匹配。
    2. 判定：DOI 命中即 verified；标题相似度 ≥0.6 matched；否则标 uncertain/unverified。
    3. 中文条目无 DOI 时降级为"题录字段核对 + 人工复核"，绝不冒充校验通过。
    4. 输出：逐条 {输入, 判定, 证据, GB/T 7714 规范格式}，供环10 定稿汇总。

注意：本环为 HITL 网关环节（hitl_required=True），执行体只产出校验结果，
人工确认动作由 M1 confirm_hitl 承载，两者解耦。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import RingType
from common.citation import format_gbt7714
from common.lit import get_lit_service
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring8")

#: 环境开关：false 时跳过真实检索（离线/测试）
_LIT_ENABLED = os.environ.get("THESIS_LIT_ENABLED", "true").lower() not in ("0", "false", "no")

#: 标题相似度阈值（≥ 判 matched）
_MATCH_THRESHOLD = 0.6


class GbtCheckItem(BaseModel):
    """单条引用校验结果。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref_title: str = Field(default="", description="原始题录标题")
    ref_doi: str = Field(default="", description="原始 DOI（如有）")
    ok: bool = Field(default=False, description="是否验证通过")
    reliability: str = Field(default="unverified", description="verified/matched/uncertain/unverified")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="核验证据（来源/相似度/匹配标题）")
    gbt7714: str = Field(default="", description="GB/T 7714 规范格式（验证通过后生成）")
    note: str = Field(default="", description="备注（中文待复核等）")


class CitationCheckResult(BaseModel):
    """环8 引用校验结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    total: int = Field(default=0, description="校验总数")
    passed: int = Field(default=0, description="通过数")
    uncertain: int = Field(default=0, description="待人工数")
    failed: int = Field(default=0, description="疑似伪引数")
    items: list[GbtCheckItem] = Field(default_factory=list, description="逐条结果")
    summary: str = Field(default="", description="整体结论")


def _extract_refs(ctx: ExecContext) -> List[Dict[str, Any]]:
    """从上下文提取参考文献列表（JSON 或纯文本行）。

    支持:
        - ctx 的 extra 字段 `references`（list[dict]）
        - ctx.outline / ctx.theme 里附带 `<<REFERENCES>>` 标记后的文本
    """
    refs: List[Dict[str, Any]] = []
    extra = getattr(ctx, "references", None)
    if isinstance(extra, list):
        for r in extra:
            if isinstance(r, dict):
                refs.append(r)
            elif isinstance(r, str) and r.strip():
                refs.append({"title": r.strip()})
    # 从 outline 注入的引用块解析（`<<REFERENCES>>` 之后每行一条）
    if not refs and ctx.outline:
        marker = "<<REFERENCES>>"
        idx = ctx.outline.find(marker)
        if idx >= 0:
            for line in ctx.outline[idx + len(marker):].splitlines():
                line = line.strip().lstrip("0123456789. ")
                if line:
                    refs.append({"title": line})
    return refs


@register_executor
class Ring8ComplianceExecutor(RingExecutor):
    """环8 引用校验执行体。

    输入：论文正文/参考文献（ctx.references 或 <<REFERENCES>> 标记）。
    输出：逐条真伪判定 + GB/T 7714 规范格式 + 整体结论。
    """

    ring_type: RingType = RingType.RING_8
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        refs = _extract_refs(ctx)
        if not refs:
            return ExecResult(
                output=CitationCheckResult(
                    total=0, summary="未提供参考文献，跳过校验（需人工先补全引用列表）"
                ).model_dump_json(indent=2),
                accept=True,
                fallbackTo=None,
                issues=["未提供引用列表，请补全后重新校验"],
                evidence={"checked": 0},
            )

        if not _LIT_ENABLED:
            # 离线/测试：跳过真实网络校验，全部标记"待人工复核"
            items = [
                GbtCheckItem(
                    ref_title=ref.get("title", ""), ref_doi=ref.get("doi", ""),
                    ok=False, reliability="uncertain",
                    evidence={"reason": "THESIS_LIT_ENABLED=false，未联网核验"},
                    note="文献检索禁用，请人工/订阅源复核",
                )
                for ref in refs
            ]
            result = CitationCheckResult(
                total=len(items), passed=0, uncertain=len(items), failed=0,
                items=items,
                summary=f"文献检索禁用（THESIS_LIT_ENABLED=false），{len(items)} 条全部待人工复核。",
            )
            return ExecResult(
                output=result.model_dump_json(indent=2),
                accept=False, fallbackTo=None,
                issues=["文献检索禁用，引用校验未完成，需人工复核"],
                evidence={"checked": len(items), "note": "THESIS_LIT_ENABLED=false"},
            )

        svc = get_lit_service()
        items: List[GbtCheckItem] = []
        passed = uncertain = failed = 0

        for ref in refs:
            title = ref.get("title", "")
            doi = ref.get("doi", "")
            # 多源核验
            verdict = svc.verify_ref({"title": title, "doi": doi, **{
                k: v for k, v in ref.items() if k in ("authors", "year", "venue")
            }})
            rel = verdict.get("reliability", "unverified")
            note = ""
            if rel == "uncertain":
                note = "中文/未命中免费源，请人工或订阅源（知网/万方/NCPSSD）复核"
                uncertain += 1
            elif rel == "unverified":
                note = "未命中任何数据源，疑似伪引，请人工核查"
                failed += 1
            else:
                passed += 1

            gbt = ""
            if verdict.get("ok") and verdict.get("item"):
                gbt = format_gbt7714(verdict["item"])

            items.append(GbtCheckItem(
                ref_title=title,
                ref_doi=doi,
                ok=bool(verdict.get("ok")),
                reliability=rel,
                evidence=verdict.get("evidence", {}),
                gbt7714=gbt,
                note=note,
            ))

        accept = failed == 0  # 存在疑似伪引则不通过（回退到环3/4 补文献）
        summary = (
            f"共校验 {len(items)} 条：通过 {passed}，待人工复核 {uncertain}，疑似伪引 {failed}。"
            + ("校验通过。" if accept else "存在疑似伪引，请修复后重新校验（回退环3 补文献）。")
        )
        result = CitationCheckResult(
            total=len(items),
            passed=passed,
            uncertain=uncertain,
            failed=failed,
            items=items,
            summary=summary,
        )

        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=accept,
            fallbackTo=3 if failed else None,  # 伪引回退到环3 文献调研补证据
            issues=[] if accept else [f"{failed} 条疑似伪引需处理"],
            evidence={
                "checked": len(items),
                "passed": passed,
                "uncertain": uncertain,
                "failed": failed,
                "sources": ["crossref", "openalex"],
                "note": "多源交叉核验，未命中不编造；中文降级人工复核",
            },
        )
