"""分节写作产物模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SectionDraftStatus(str, Enum):
    GENERATED = "GENERATED"
    AUTO_REJECTED = "AUTO_REJECTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class SectionDraft:
    section_draft_id: str
    task_id: str
    section_id: str
    version: int
    status: SectionDraftStatus
    title: str
    content: str
    content_hash: str
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    result_ids: tuple[str, ...] = ()
    upstream_artifact_ids: tuple[str, ...] = ()
    context_manifest: dict[str, Any] = field(default_factory=dict)
    gate_report: dict[str, Any] = field(default_factory=dict)
    stale_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        for key in (
            "claim_ids", "evidence_ids", "result_ids", "upstream_artifact_ids"
        ):
            value[key] = list(value[key])
        return value
