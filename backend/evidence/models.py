"""论文证据账本的领域对象。

来源（Source）只证明“这篇材料存在”；摘录（Excerpt）才是可定位、可复核的
证据；论断（Claim）通过显式链接引用证据。三者分开，避免把摘要或题录误当成
能够支撑正文结论的原文证据。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SourceVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    METADATA_VERIFIED = "METADATA_VERIFIED"
    FULLTEXT_AVAILABLE = "FULLTEXT_AVAILABLE"
    CONTENT_VERIFIED = "CONTENT_VERIFIED"
    RETRACTED_FLAG = "RETRACTED_FLAG"
    EXCLUDED = "EXCLUDED"


class EvidenceReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    BACKGROUND = "BACKGROUND"
    METHOD = "METHOD"


class ClaimType(str, Enum):
    FACTUAL = "FACTUAL"
    NUMERIC = "NUMERIC"
    METHOD = "METHOD"
    INTERPRETIVE = "INTERPRETIVE"
    CONTRIBUTION = "CONTRIBUTION"


class ClaimStatus(str, Enum):
    UNSUPPORTED = "UNSUPPORTED"
    SUPPORTED = "SUPPORTED"
    DISPUTED = "DISPUTED"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    task_id: str
    canonical_key: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    provider: str = ""
    verification_status: SourceVerificationStatus = SourceVerificationStatus.UNVERIFIED
    reliability: str = "uncertain"
    file_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["authors"] = list(self.authors)
        value["verification_status"] = self.verification_status.value
        return value


@dataclass(frozen=True)
class EvidenceExcerpt:
    evidence_id: str
    task_id: str
    source_id: str
    quote: str
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""
    char_start: int | None = None
    char_end: int | None = None
    content_hash: str = ""
    review_status: EvidenceReviewStatus = EvidenceReviewStatus.NEEDS_REVIEW
    review_actor: str = ""
    review_reason: str = ""
    created_by: str = "agent"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["review_status"] = self.review_status.value
        return value


@dataclass(frozen=True)
class Claim:
    claim_id: str
    task_id: str
    source_key: str
    artifact_id: str
    section_id: str
    text: str
    claim_type: ClaimType = ClaimType.FACTUAL
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["claim_type"] = self.claim_type.value
        return value


@dataclass(frozen=True)
class EvidenceLink:
    link_id: str
    task_id: str
    claim_id: str
    evidence_id: str
    relation: EvidenceRelation
    rationale: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["relation"] = self.relation.value
        return value
