"""引用与证据链的分层可信度派生模型。"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any


class TrustCheckStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class CitationTrustTier(str, Enum):
    NONE = "NONE"
    STRUCTURE = "STRUCTURE"
    METADATA = "METADATA"
    EVIDENCE = "EVIDENCE"


_TIER_LABELS = {
    CitationTrustTier.NONE: "未形成可声明的通过层级",
    CitationTrustTier.STRUCTURE: "结构已检查",
    CitationTrustTier.METADATA: "题录/元数据已核验",
    CitationTrustTier.EVIDENCE: "正文证据链已核验",
}

_DIMENSION_LABELS = {
    "structure": "结构",
    "metadata": "题录/元数据",
    "evidence": "正文证据",
}


def build_citation_trust_assessment(
    *,
    structure: TrustCheckStatus,
    metadata: TrustCheckStatus,
    evidence: TrustCheckStatus,
    summaries: dict[str, str] | None = None,
) -> dict[str, Any]:
    """生成单调的三档可信度；不将流程通过冒充学术证实。"""
    for value in (structure, metadata, evidence):
        if not isinstance(value, TrustCheckStatus):
            raise ValueError("trust status必须是TrustCheckStatus")
    if metadata == TrustCheckStatus.PASSED and structure != TrustCheckStatus.PASSED:
        raise ValueError("元数据通过时结构必须已通过")
    if evidence == TrustCheckStatus.PASSED and (
        structure != TrustCheckStatus.PASSED
        or metadata != TrustCheckStatus.PASSED
    ):
        raise ValueError("证据通过时结构和元数据必须已通过")

    if evidence == TrustCheckStatus.PASSED:
        highest = CitationTrustTier.EVIDENCE
    elif metadata == TrustCheckStatus.PASSED:
        highest = CitationTrustTier.METADATA
    elif structure == TrustCheckStatus.PASSED:
        highest = CitationTrustTier.STRUCTURE
    else:
        highest = CitationTrustTier.NONE

    summaries = summaries or {}
    dimensions = {}
    for key, status in (
        ("structure", structure),
        ("metadata", metadata),
        ("evidence", evidence),
    ):
        dimensions[key] = {
            "label": _DIMENSION_LABELS[key],
            "status": status.value,
            "summary": str(summaries.get(key, "")),
        }

    warning = ""
    if highest != CitationTrustTier.EVIDENCE:
        warning = (
            "当前结果不等于正文论断已获得全文证据支撑；"
            "请查看正文证据档状态。"
        )
    return {
        "schema_version": "citation-trust-v1",
        "highest_tier": highest.value,
        "highest_tier_label": _TIER_LABELS[highest],
        "dimensions": dimensions,
        "author_review": {
            "label": "作者复核",
            "status": "PENDING",
            "summary": "等待作者确认环8产物",
        },
        "warning": warning,
    }


def with_author_review(
    assessment: dict[str, Any], *, approved: bool, reason: str = ""
) -> dict[str, Any]:
    """返回带作者审批结果的新摘要，不原地修改。"""
    value = deepcopy(assessment)
    value["author_review"] = {
        "label": "作者复核",
        "status": "APPROVED" if approved else "REJECTED",
        "summary": reason.strip() or (
            "作者已确认环8产物"
            if approved
            else "作者已驳回环8产物"
        ),
    }
    return value
