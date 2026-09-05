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
class SectionContract:
    """嵌入批准大纲叶子节点的不可变分节写作合同。"""

    section_id: str
    title: str
    purpose: str
    canon_hash: str
    input_artifact_ids: tuple[str, ...] = ()
    allowed_claim_keys: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    required_evidence_ids: tuple[str, ...] = ()
    required_result_ids: tuple[str, ...] = ()
    requires_verified_results: bool = False
    validation_checks: tuple[str, ...] = ()
    schema_version: str = "m3"

    def __post_init__(self) -> None:
        if not self.section_id.strip():
            raise ValueError("SectionContract section_id 不能为空")
        if not self.title.strip():
            raise ValueError("SectionContract title 不能为空")
        if not self.purpose.strip():
            raise ValueError("SectionContract purpose 不能为空")
        if len(self.canon_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.canon_hash.lower()
        ):
            raise ValueError("SectionContract canon_hash 非法")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "section_id": self.section_id,
            "title": self.title,
            "purpose": self.purpose,
            "canon_hash": self.canon_hash,
            "input_artifact_ids": list(self.input_artifact_ids),
            "allowed_claim_keys": list(self.allowed_claim_keys),
            "forbidden_claims": list(self.forbidden_claims),
            "evidence_requirements": list(self.evidence_requirements),
            "required_evidence_ids": list(self.required_evidence_ids),
            "required_result_ids": list(self.required_result_ids),
            "requires_verified_results": self.requires_verified_results,
            "validation_checks": list(self.validation_checks),
        }

    @property
    def contract_hash(self) -> str:
        encoded = json.dumps(
            self._body(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "SectionContract":
        if not isinstance(value, dict):
            raise ValueError("SectionContract 必须是对象")
        list_fields = {
            "input_artifact_ids",
            "allowed_claim_keys",
            "forbidden_claims",
            "evidence_requirements",
            "required_evidence_ids",
            "required_result_ids",
            "validation_checks",
        }
        allowed_fields = {
            "schema_version",
            "section_id",
            "title",
            "purpose",
            "canon_hash",
            "contract_hash",
            "requires_verified_results",
            *list_fields,
        }
        unknown_fields = sorted(set(value) - allowed_fields)
        if unknown_fields:
            raise ValueError(f"SectionContract 包含未知字段: {unknown_fields}")
        malformed_lists = sorted(
            field_name
            for field_name in list_fields
            if field_name in value
            and not isinstance(value[field_name], (list, tuple))
        )
        if malformed_lists:
            raise ValueError(f"SectionContract 列表字段类型非法: {malformed_lists}")
        if not isinstance(value.get("requires_verified_results", False), bool):
            raise ValueError("SectionContract requires_verified_results 必须是布尔值")
        contract = cls(
            schema_version=str(value.get("schema_version", "")),
            section_id=str(value.get("section_id", "")),
            title=str(value.get("title", "")),
            purpose=str(value.get("purpose", "")),
            canon_hash=str(value.get("canon_hash", "")).lower(),
            input_artifact_ids=unique_strings(value.get("input_artifact_ids")),
            allowed_claim_keys=unique_strings(value.get("allowed_claim_keys")),
            forbidden_claims=unique_strings(value.get("forbidden_claims")),
            evidence_requirements=unique_strings(value.get("evidence_requirements")),
            required_evidence_ids=unique_strings(value.get("required_evidence_ids")),
            required_result_ids=unique_strings(value.get("required_result_ids")),
            requires_verified_results=bool(value.get("requires_verified_results", False)),
            validation_checks=unique_strings(value.get("validation_checks")),
        )
        if contract.schema_version != "m3":
            raise ValueError("SectionContract schema_version 不受支持")
        if str(value.get("contract_hash", "")).lower() != contract.contract_hash:
            raise ValueError("SectionContract contract_hash 不匹配")
        return contract


def section_contract_set_hash(contracts: Iterable[SectionContract]) -> str:
    items = sorted(
        (
            {"section_id": contract.section_id, "contract_hash": contract.contract_hash}
            for contract in contracts
        ),
        key=lambda item: item["section_id"],
    )
    encoded = json.dumps(
        items, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
