# -*- coding: utf-8 -*-
"""环10 定稿汇总执行体（M2 二期：全环验收汇总 + 材料对齐 + 交付清单）。

职责：汇总环1~9 各环节验收状态，做最终一致性检查（题目/摘要/正文/结论表述一致），
判定材料齐备性，输出交付清单（论文 docx + 参考文献 + 验收报告 + 待补材料）。

设计要点：
    1. 输入：ctx 的 artifacts（dict，含各环产物/验收状态）+ title。
    2. 验收汇总：对环1/2/3/4/5/6/7/8/9 标记"通过/未跑/有问题"。
    3. 一致性检查：题目（title）+ 摘要摘要 + 正文首章 + 结论段是否协调（粗粒度关键词）。
    4. 材料齐备：前置件（封面/声明/中英摘要/目录）+ 正文 + 参考文献 + 附件/答辩材料标记。
    5. 有未过环 → accept=False（列出哪些环）；全过 → 放行交付（HITL 人工确认由 M1 承载）。
    6. 保留 HITL 标志（环10 网关），人工确认由 M1 confirm_hitl。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring10")

#: 各环节名称（验收汇总用）
_RING_NAMES: Dict[int, str] = {
    1: "选题", 2: "开题评审", 3: "文献调研", 4: "综述评审",
    5: "大纲", 6: "撰写", 7: "润色", 8: "引用校验", 9: "排版",
}

#: 材料清单（必备）
_REQUIRED_MATERIALS: List[str] = [
    "论文正文（docx）",
    "封面/声明",
    "中文摘要",
    "英文摘要",
    "目录",
    "参考文献表",
]


class RingStatus(BaseModel):
    """单环验收状态。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ring_no: int = Field(default=0, description="环号")
    name: str = Field(default="", description="环节名")
    status: str = Field(default="未跑", description="通过/未跑/有问题")


class FinalCheckIssue(BaseModel):
    """定稿问题。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str = Field(default="", description="consistency/material/acceptance")
    message: str = Field(default="", description="描述")


class FinalDeliveryResult(BaseModel):
    """环10 定稿汇总产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="论文题目")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    rings: list[RingStatus] = Field(default_factory=list, description="各环验收状态")
    consistency: list[FinalCheckIssue] = Field(default_factory=list, description="一致性检查")
    materials_ready: list[str] = Field(default_factory=list, description="已备材料")
    materials_missing: list[str] = Field(default_factory=list, description="待补材料")
    delivery_checklist: list[str] = Field(default_factory=list, description="交付清单")
    summary: str = Field(default="", description="结论摘要")


def _check_consistency(artifacts: Dict[str, Any], title: str) -> List[FinalCheckIssue]:
    """一致性：题目关键词与摘要/正文/结论协调（粗粒度，仅警示不强判）。"""
    issues: List[FinalCheckIssue] = []
    if not title:
        issues.append(FinalCheckIssue(category="consistency", message="题目为空"))
        return issues
    # 题目核心词（中文无空格连写，用 2-字滑窗取样避免整段当词；全部取样）
    clean = re.sub(r"[^一-鿿A-Za-z0-9]+", "", title)
    keywords = [clean[i:i + 2] for i in range(len(clean) - 1)][:20]
    # 摘要（环1 推荐/环6 正文首章）
    ring1 = artifacts.get("ring1") or {}
    ring6 = artifacts.get("ring6") or {}
    abs_text = (ring1.get("recommendation", "") if isinstance(ring1, dict) else "") + \
               (ring6.get("content", "") if isinstance(ring6, dict) else "")
    # 判定：≥30% 双字窗口命中算一致（宽松，仅警示）
    hit = sum(1 for k in keywords if k in abs_text)
    if keywords and hit / max(len(keywords), 1) < 0.3:
        issues.append(FinalCheckIssue(
            category="consistency",
            message=f"题目核心词「{clean[:8]}」未在摘要/正文出现，注意题目与内容一致性"
        ))
    return issues


def _materials_status(artifacts: Dict[str, Any]) -> tuple[List[str], List[str]]:
    """材料齐备判定。"""
    ready, missing = [], []
    ring9 = artifacts.get("ring9") or {}
    docx_done = bool(artifacts.get("docx") or ring9)
    if docx_done:
        ready.append("论文正文（docx）")
    else:
        missing.append("论文正文（docx）")
    # 封面/摘要/目录：由 docx 模板占位符决定（环5 大纲有章节说明即可视为结构完整）
    if isinstance(ring9, dict) and ring9.get("compliant"):
        ready.extend(["封面/声明", "中文摘要", "英文摘要", "目录"])
    else:
        missing.extend(["封面/声明", "中文摘要", "英文摘要", "目录"])
    # 参考文献表：环8 通过则有
    ring8 = artifacts.get("ring8") or {}
    if isinstance(ring8, dict) and ring8.get("total", 0) > 0 and ring8.get("passed", 0) > 0:
        ready.append("参考文献表")
    else:
        missing.append("参考文献表")
    return ready, missing


@register_executor
class Ring10DeliveryExecutor(RingExecutor):
    """环10 定稿汇总执行体（验收汇总 + 一致性 + 材料清单，HITL 标志）。"""

    ring_type: RingType = RingType.RING_10
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        artifacts: Dict[str, Any] = getattr(ctx, "artifacts", None) or {}
        title = (getattr(ctx, "theme", "") or "").strip() or "（未命名论文）"

        # 1. 各环验收汇总
        rings: List[RingStatus] = []
        failed_rings: List[int] = []
        for no, name in _RING_NAMES.items():
            art = artifacts.get(f"ring{no}")
            if art is None or (isinstance(art, dict) and not art):
                # 未跑（无产物 / 空 dict）
                status = "未跑"
                failed_rings.append(no)
            elif isinstance(art, dict) and art.get("compliant"):
                status = "通过"
            elif isinstance(art, dict):
                status = "有问题"
                failed_rings.append(no)
            else:
                status = "未跑"
                failed_rings.append(no)
            rings.append(RingStatus(ring_no=no, name=name, status=status))

        # 2. 一致性检查
        consistency = _check_consistency(artifacts, title)

        # 3. 材料齐备
        ready, missing = _materials_status(artifacts)

        # 4. 交付清单
        checklist = [
            f"论文：《{title}》（{ctx.degree.label}）",
            "验收报告（本环节输出）",
        ] + [f"待补：{m}" for m in missing] if missing else [
            f"论文：《{title}》（{ctx.degree.label}）",
            "论文 docx（排版合规）",
            "参考文献表（GB/T 7714）",
            "验收报告（全部环通过）",
        ]

        all_pass = not failed_rings and not consistency and not missing
        summary = (
            f"全部环节通过（环1~9），材料齐备，可提交换导师/学校审核。"
            if all_pass else
            f"未通过项：{'、'.join(f'环{n}' for n in failed_rings) or '无'}；"
            f"待补材料：{'、'.join(missing) or '无'}。补齐后再交付。"
        )
        result = FinalDeliveryResult(
            title=title,
            degree=ctx.degree,
            rings=rings,
            consistency=consistency,
            materials_ready=ready,
            materials_missing=missing,
            delivery_checklist=checklist,
            summary=summary,
        )

        issues = [] if all_pass else (
            [f"环{n}未通过" for n in failed_rings] + [i.message for i in consistency] +
            [f"待补：{m}" for m in missing]
        )
        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=all_pass,
            fallbackTo=None,  # 各环问题由各自环节回退，此处仅汇总
            issues=issues,
            evidence={
                "rings_checked": len(rings),
                "failed": failed_rings,
                "consistency_issues": len(consistency),
                "materials_missing": missing,
                "note": "验收汇总 + 一致性检查；HITL 人工确认由 M1 承载",
            },
        )
