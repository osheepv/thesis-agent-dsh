"""论文全流程中的不可变产物、上下文清单和审批类型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ArtifactKind(str, Enum):
    """跨阶段共享的核心产物类型。"""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    TOPIC_PROPOSAL = "TOPIC_PROPOSAL"
    FEASIBILITY_REVIEW = "FEASIBILITY_REVIEW"
    LITERATURE_CORPUS = "LITERATURE_CORPUS"
    EVIDENCE_SYNTHESIS = "EVIDENCE_SYNTHESIS"
    RESEARCH_PROTOCOL = "RESEARCH_PROTOCOL"
    EXPERIMENT_MANUAL = "EXPERIMENT_MANUAL"
    EXPERIMENT_RUN = "EXPERIMENT_RUN"
    RESULT_LEDGER = "RESULT_LEDGER"
    ARGUMENT_MAP = "ARGUMENT_MAP"
    OUTLINE = "OUTLINE"
    SECTION_DRAFT = "SECTION_DRAFT"
    REVISION = "REVISION"
    CITATION_AUDIT = "CITATION_AUDIT"
    FORMATTING_AUDIT = "FORMATTING_AUDIT"
    FORMATTED_MANUSCRIPT = "FORMATTED_MANUSCRIPT"
    DELIVERY_MANIFEST = "DELIVERY_MANIFEST"


class ArtifactStatus(str, Enum):
    """产物生命周期；正文内容本身从不原地覆盖。"""

    GENERATED = "GENERATED"
    AUTO_REJECTED = "AUTO_REJECTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ContextManifest:
    """一次 Agent 调用使用的可重放上下文清单。"""

    prompt_id: str = ""
    prompt_version: str = ""
    model: str = ""
    input_artifact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    token_budget: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retrieval_query_hash: str = ""
    job_id: str = ""
    cost_budget: float = 0.0
    cost_used: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ContextManifest":
        value = value or {}
        return cls(
            prompt_id=str(value.get("prompt_id", "")),
            prompt_version=str(value.get("prompt_version", "")),
            model=str(value.get("model", "")),
            input_artifact_ids=tuple(value.get("input_artifact_ids", ()) or ()),
            evidence_ids=tuple(value.get("evidence_ids", ()) or ()),
            token_budget=int(value.get("token_budget", 0) or 0),
            input_tokens=int(value.get("input_tokens", 0) or 0),
            output_tokens=int(value.get("output_tokens", 0) or 0),
            retrieval_query_hash=str(value.get("retrieval_query_hash", "")),
            job_id=str(value.get("job_id", "")),
            cost_budget=float(value.get("cost_budget", 0) or 0),
            cost_used=float(value.get("cost_used", 0) or 0),
        )


@dataclass(frozen=True)
class Artifact:
    """一个确定版本的阶段产物。"""

    artifact_id: str
    task_id: str
    stage_no: int
    kind: ArtifactKind
    version: int
    status: ArtifactStatus
    payload: dict[str, Any]
    content_hash: str
    dependency_ids: tuple[str, ...] = ()
    context_manifest: ContextManifest = field(default_factory=ContextManifest)
    gate_report: dict[str, Any] = field(default_factory=dict)
    stale_reason: str = ""
    source_event_id: str = ""
    created_at: str = ""
    updated_at: str = ""
