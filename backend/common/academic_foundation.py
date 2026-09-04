"""只读学术基础投影的数据契约。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class EvidenceState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    DISPUTED = "DISPUTED"
    INVALID_SOURCE = "INVALID_SOURCE"


class VerificationStrength(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    LOCATED_APPROVED = "LOCATED_APPROVED"
    CONTENT_VERIFIED = "CONTENT_VERIFIED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class CanonicalArtifactRef:
    artifact_id: str
    kind: str
    version: int
    status: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalSourceRef:
    source_id: str
    verification_status: str
    record_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceTableRow:
    claim_key: str
    claim_id: str
    section_id: str
    text: str
    claim_type: str
    role: str
    epistemic_intent: str
    evidence_state: EvidenceState
    verification_strength: VerificationStrength
    risk_level: RiskLevel
    evidence_requirements: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    invalid_source_ids: tuple[str, ...] = ()
    invalid_evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "evidence_state",
            "verification_strength",
            "risk_level",
        ):
            value[key] = value[key].value
        for key in (
            "evidence_requirements",
            "source_ids",
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "invalid_source_ids",
            "invalid_evidence_ids",
        ):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class ResearchCanonSnapshot:
    task_id: str
    schema_version: str = "m2"
    artifact_refs: tuple[CanonicalArtifactRef, ...] = ()
    source_refs: tuple[CanonicalSourceRef, ...] = ()
    scope_boundaries: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    unresolved_claims: tuple[str, ...] = ()
    verified_result_ids: tuple[str, ...] = ()
    evidence_table: tuple[EvidenceTableRow, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    blocking_claim_ids: tuple[str, ...] = ()

    def _body(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "schema_version": self.schema_version,
            "artifact_refs": [item.to_dict() for item in self.artifact_refs],
            "source_refs": [item.to_dict() for item in self.source_refs],
            "scope_boundaries": list(self.scope_boundaries),
            "forbidden_claims": list(self.forbidden_claims),
            "unresolved_claims": list(self.unresolved_claims),
            "verified_result_ids": list(self.verified_result_ids),
            "evidence_table": [item.to_dict() for item in self.evidence_table],
            "missing_artifacts": list(self.missing_artifacts),
            "blocking_claim_ids": list(self.blocking_claim_ids),
        }

    @property
    def canon_hash(self) -> str:
        encoded = json.dumps(
            self._body(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def can_write(self) -> bool:
        return not self.missing_artifacts and bool(self.evidence_table) and not self.blocking_claim_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._body(),
            "canon_hash": self.canon_hash,
            "can_write": self.can_write,
        }


def source_record_hash(
    *, source_id: str, verification_status: str, file_hash: str
) -> str:
    value = "|".join((source_id, verification_status, file_hash))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def unique_strings(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))
