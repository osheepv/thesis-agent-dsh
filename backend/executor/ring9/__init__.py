# -*- coding: utf-8 -*-
"""环9 格式排版执行体（M2 二期：docx 版式合规检查）。

职责：对生成的 docx 做版式合规检查（页面/字体/段落/结构/OOXML）——
    只查不改（对齐规范环9：前置件齐全、字体字号/行距/页边距/页码合规）。
    无 HARD 问题 → 放行；有 HARD → accept=False，提示回退 docx 生成/换模板。

设计要点：
    1. 输入：ctx 的 docx_path（生成产物路径）+ template_path（可选模板基准）。
    2. 用 thesis_docx.compliance.DocxComplianceChecker（自研规则库 + 模板抽取）。
    3. 输出：ComplianceReport（compliant / issues / rules_used）。
    4. 无 docx_path（尚未生成）：提示先跑 docx 生成。
    5. 本环自动执行（非 HITL），接受=逐项合规。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring9")


class LayoutIssue(BaseModel):
    """单条排版问题。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str = Field(default="", description="page/font/paragraph/structure/ooxml")
    severity: str = Field(default="SOFT", description="HARD/SOFT")
    message: str = Field(default="", description="描述")


class LayoutReport(BaseModel):
    """环9 排版合规报告。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    compliant: bool = Field(default=False, description="是否合规（无 HARD）")
    docx_path: str = Field(default="", description="检查的 docx 路径")
    rules_used: str = Field(default="", description="default/template")
    issues: list[LayoutIssue] = Field(default_factory=list, description="问题列表")
    summary: str = Field(default="", description="结论摘要")


@register_executor
class Ring9TypesetExecutor(RingExecutor):
    """环9 格式排版执行体（docx 版式合规检查，只查不改）。"""

    ring_type: RingType = RingType.RING_9
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        docx_path = (getattr(ctx, "docx_path", "") or "").strip()
        template_path = (getattr(ctx, "template_path", "") or "").strip()

        if not docx_path or not os.path.exists(docx_path):
            return ExecResult(
                output=LayoutReport(
                    compliant=False,
                    summary="未找到 docx 产物，请先运行 docx 生成后再排版检查",
                ).model_dump_json(indent=2),
                accept=False,
                fallbackTo=None,
                issues=["缺少 docx 产物，请先生成"],
                evidence={"checked": 0, "note": "docx_path 未提供"},
            )

        try:
            from thesis_docx.compliance import DocxComplianceChecker

            checker = DocxComplianceChecker()
            report = checker.check(docx_path, template_path=template_path or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("环9 排版检查失败: %s", exc)
            return ExecResult(
                output=LayoutReport(
                    compliant=False,
                    docx_path=docx_path,
                    summary=f"排版检查异常：{exc}",
                ).model_dump_json(indent=2),
                accept=False,
                fallbackTo=None,
                issues=[f"排版检查异常：{exc}"],
                evidence={"checked": 0},
            )

        d = report.to_dict()
        issues = [LayoutIssue(**i) for i in d["issues"]]
        summary = (
            f"版式合规（{d['hard_count']} 项硬伤，{d['issue_count'] - d['hard_count']} 项建议）"
            if d["compliant"] else
            f"发现 {d['hard_count']} 项硬伤（见 issues），请调整模板/格式后重新生成"
        )
        result = LayoutReport(
            compliant=d["compliant"],
            docx_path=docx_path,
            rules_used=d["rules_used"],
            issues=issues,
            summary=summary,
        )

        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=d["compliant"],
            fallbackTo=None,  # HARD 时提示重生成（不改内容，无明确回退环）
            issues=[] if d["compliant"] else [i["message"] for i in d["issues"] if i["severity"] == "HARD"],
            evidence={
                "checked": True,
                "compliant": d["compliant"],
                "hard_count": d["hard_count"],
                "rules_used": d["rules_used"],
                "note": "只查不改（内容由模板渲染保持）；页码域/首行缩进修建议提交端处理",
            },
        )
