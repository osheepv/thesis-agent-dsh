"""M2 学术基础只读投影与证据表契约测试。"""

from __future__ import annotations

import pytest

from artifacts import ArtifactKind, ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.academic_foundation import SectionContract, section_contract_set_hash
from common.aicoding.enums import Degree
from evidence import (
    ClaimType,
    EvidenceLedger,
    EvidenceRelation,
    SourceVerificationStatus,
)
from research import ResearchExecutionRegistry


def test_section_contract_hash_round_trip_and_tamper_detection():
    contract = SectionContract(
        section_id="2.1",
        title="证据分析",
        purpose="基于批准证据回答研究问题",
        canon_hash="a" * 64,
        input_artifact_ids=("ART-1", "ART-2"),
        allowed_claim_keys=("ROOT",),
        forbidden_claims=("未经核验的结论",),
        evidence_requirements=("原文页码",),
        required_evidence_ids=("EVD-1",),
        validation_checks=("ALLOWED_CLAIMS_ONLY",),
    )
    payload = contract.to_dict()

    assert SectionContract.from_dict(payload) == contract
    assert len(section_contract_set_hash([contract])) == 64
    payload["purpose"] = "被篡改"
    with pytest.raises(ValueError, match="contract_hash"):
        SectionContract.from_dict(payload)
    unknown = contract.to_dict()
    unknown["evidence_backed"] = True
    with pytest.raises(ValueError, match="未知字段"):
        SectionContract.from_dict(unknown)


def _orchestration() -> MainOrchestration:
    return MainOrchestration(
        artifact_registry=ArtifactRegistry(),
        evidence_ledger=EvidenceLedger(),
        research_registry=ResearchExecutionRegistry(),
    )


def _task(orchestration: MainOrchestration, suffix: str = "m2") -> str:
    return orchestration.create_task(
        f"学术基础-{suffix}", Degree.MASTER, "计算机科学", session_id=f"{suffix}-session"
    ).data["task_id"]


def _approve_artifact(
    orchestration: MainOrchestration,
    task_id: str,
    kind: ArtifactKind,
    stage_no: int,
    payload: dict,
):
    artifact = orchestration._artifacts.create_version(
        task_id=task_id,
        stage_no=stage_no,
        kind=kind,
        payload=payload,
    )
    artifact = orchestration._artifacts.submit_auto_gate(artifact.artifact_id, passed=True)
    return orchestration._artifacts.decide(artifact.artifact_id, approved=True)


def _foundation_task(orchestration: MainOrchestration) -> tuple[str, dict, str]:
    task_id = _task(orchestration)
    _approve_artifact(
        orchestration,
        task_id,
        ArtifactKind.PROJECT_MEMORY,
        1,
        {
            "research_questions": ["证据投影是否降低引用错误？"],
            "scope_boundaries": ["只讨论可复核的论文写作流程"],
            "forbidden_claims": ["不得声称自动替代作者判断"],
            "unresolved_claims": ["尚未完成跨学科复现"],
        },
    )
    _approve_artifact(
        orchestration,
        task_id,
        ArtifactKind.RESEARCH_PROTOCOL,
        5,
        {"title": "M2 protocol", "method": "SYSTEM_BUILD"},
    )
    argument = _approve_artifact(
        orchestration,
        task_id,
        ArtifactKind.ARGUMENT_MAP,
        5,
        {
            "title": "M2 argument map",
            "research_questions": ["证据投影是否降低引用错误？"],
            "claims": [
                {
                    "claim_key": "ROOT",
                    "text": "可定位证据有助于降低引用错误",
                    "section_id": "1.2",
                    "claim_type": "CONTRIBUTION",
                    "role": "THESIS",
                    "epistemic_intent": "ASSERTION",
                    "parent_keys": [],
                    "evidence_requirements": ["引用错误率"],
                },
                {
                    "claim_key": "H1",
                    "text": "该结论仍需跨学科复现",
                    "section_id": "5.3",
                    "claim_type": "INTERPRETIVE",
                    "role": "LIMITATION",
                    "epistemic_intent": "HYPOTHESIS",
                    "parent_keys": ["ROOT"],
                    "evidence_requirements": [],
                },
            ],
        },
    )
    _approve_artifact(
        orchestration,
        task_id,
        ArtifactKind.RESULT_LEDGER,
        6,
        {
            "results": [
                {
                    "result_id": "RES-SECRET",
                    "metric": "错误率",
                    "value": "0.12",
                    "raw_result_text": "must never appear in the canon snapshot",
                }
            ]
        },
    )
    orchestration._sync_argument_map_claims(task_id, argument)
    root_claim = orchestration._evidence.list_claims(task_id, artifact_id=argument.artifact_id)[0]
    return task_id, argument.payload, root_claim.claim_id


def _register_evidence(
    orchestration: MainOrchestration,
    task_id: str,
    *,
    status: SourceVerificationStatus,
    quote: str | None = None,
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
):
    source = orchestration._evidence.register_source(
        task_id=task_id,
        title="source",
        doi=f"10.1000/{source_id_suffix(status)}",
        verification_status=status,
    )
    if quote is None:
        return source, None
    excerpt = orchestration._evidence.add_excerpt(
        task_id=task_id,
        source_id=source.source_id,
        quote=quote,
        page_start=1,
    )
    orchestration._evidence.review_excerpt(task_id, excerpt.evidence_id, approved=True)
    return source, (excerpt, relation)


def source_id_suffix(status: SourceVerificationStatus) -> str:
    return status.value.lower().replace("_", "-")


def test_academic_foundation_is_read_only_and_does_not_leak_payload_bodies():
    orchestration = _orchestration()
    task_id, argument_payload, root_claim_id = _foundation_task(orchestration)
    source, evidence = _register_evidence(
        orchestration,
        task_id,
        status=SourceVerificationStatus.METADATA_VERIFIED,
        quote="A located excerpt approved by the author.",
    )
    excerpt, relation = evidence
    orchestration._evidence.link_evidence(
        task_id=task_id,
        claim_id=root_claim_id,
        evidence_id=excerpt.evidence_id,
        relation=relation,
    )

    before = len(orchestration._artifacts.list_task(task_id))
    before_sources = len(orchestration._evidence.list_sources(task_id))
    result = orchestration.get_academic_foundation(task_id)
    after = len(orchestration._artifacts.list_task(task_id))
    after_sources = len(orchestration._evidence.list_sources(task_id))

    assert before == after
    assert before_sources == after_sources
    data = result.data
    assert data["task_id"] == task_id
    assert data["schema_version"] == "m2"
    assert data["source_refs"][0]["source_id"] == source.source_id
    root = next(row for row in data["evidence_table"] if row["claim_key"] == "ROOT")
    assert root["epistemic_intent"] == "ASSERTION"
    assert root["evidence_state"] == "SUPPORTED"
    assert root["verification_strength"] == "LOCATED_APPROVED"
    serialized = str(data)
    assert "A located excerpt" not in serialized
    assert "must never appear in the canon snapshot" not in serialized
    assert "raw_result_text" not in serialized
    assert "payload" not in data
    assert root_claim_id not in data["blocking_claim_ids"]


def test_metadata_only_source_without_excerpt_is_not_evidence_backed():
    orchestration = _orchestration()
    task_id, _, _ = _foundation_task(orchestration)
    _register_evidence(
        orchestration,
        task_id,
        status=SourceVerificationStatus.METADATA_VERIFIED,
        quote=None,
    )

    data = orchestration.get_academic_foundation(task_id).data
    root = next(row for row in data["evidence_table"] if row["claim_key"] == "ROOT")
    assert root["evidence_state"] == "UNSUPPORTED"
    assert root["verification_strength"] == "UNVERIFIED"
    assert root["risk_level"] == "HIGH"
    assert root["claim_id"] in data["blocking_claim_ids"]


def test_content_verified_support_gets_stronger_verification_and_contradiction_blocks():
    orchestration = _orchestration()
    task_id, _, root_claim_id = _foundation_task(orchestration)
    source, evidence = _register_evidence(
        orchestration,
        task_id,
        status=SourceVerificationStatus.CONTENT_VERIFIED,
        quote="Verified support.",
    )
    excerpt, _ = evidence
    orchestration._evidence.link_evidence(
        task_id=task_id,
        claim_id=root_claim_id,
        evidence_id=excerpt.evidence_id,
        relation=EvidenceRelation.SUPPORTS,
    )
    _, contradiction = _register_evidence(
        orchestration,
        task_id,
        status=SourceVerificationStatus.CONTENT_VERIFIED,
        quote="Verified contradiction.",
        relation=EvidenceRelation.CONTRADICTS,
    )
    contradiction_excerpt, _ = contradiction
    orchestration._evidence.link_evidence(
        task_id=task_id,
        claim_id=root_claim_id,
        evidence_id=contradiction_excerpt.evidence_id,
        relation=EvidenceRelation.CONTRADICTS,
    )

    data = orchestration.get_academic_foundation(task_id).data
    root = next(row for row in data["evidence_table"] if row["claim_key"] == "ROOT")
    assert root["evidence_state"] == "DISPUTED"
    assert root["verification_strength"] == "CONTENT_VERIFIED"
    assert root["risk_level"] == "HIGH"
    assert root["claim_id"] in data["blocking_claim_ids"]
    assert source.source_id in root["source_ids"]


def test_retracted_or_excluded_sources_cannot_support_a_claim():
    orchestration = _orchestration()
    task_id, _, root_claim_id = _foundation_task(orchestration)
    source, evidence = _register_evidence(
        orchestration,
        task_id,
        status=SourceVerificationStatus.EXCLUDED,
        quote="Excluded support.",
    )
    excerpt, _ = evidence
    orchestration._evidence.link_evidence(
        task_id=task_id,
        claim_id=root_claim_id,
        evidence_id=excerpt.evidence_id,
        relation=EvidenceRelation.SUPPORTS,
    )

    data = orchestration.get_academic_foundation(task_id).data
    root = next(row for row in data["evidence_table"] if row["claim_key"] == "ROOT")
    assert root["evidence_state"] == "INVALID_SOURCE"
    assert root["verification_strength"] == "UNVERIFIED"
    assert root["risk_level"] == "HIGH"
    assert root["invalid_source_ids"] == [source.source_id]


def test_academic_foundation_only_uses_current_approved_versions_and_is_task_isolated():
    orchestration = _orchestration()
    task_id, _, _ = _foundation_task(orchestration)
    other_task = _task(orchestration, "other")
    other_source, _ = _register_evidence(
        orchestration,
        other_task,
        status=SourceVerificationStatus.CONTENT_VERIFIED,
        quote="other task",
    )

    data = orchestration.get_academic_foundation(task_id).data
    refs = {item["source_id"] for item in data["source_refs"]}
    assert other_source.source_id not in refs
    assert all(item["status"] == "APPROVED" for item in data["artifact_refs"])
    assert data["missing_artifacts"] == []


def test_academic_foundation_console_endpoint_is_read_only():
    from application.main import build_app
    from fastapi.testclient import TestClient

    orchestration = _orchestration()
    app = build_app(orchestration=orchestration)
    client = TestClient(app)
    created = client.post(
        "/api/v1/console/tasks",
        json={
            "title": "学术基础接口",
            "degree": "MASTER",
            "subject_field": "计算机科学",
            "session_id": "academic-foundation-api",
        },
    ).json()
    task_id = created["data"]["task_id"]
    response = client.get(
        f"/api/v1/console/tasks/{task_id}/academic-foundation",
        params={"session_id": "academic-foundation-api", "evidence_backed": "true"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"]["evidence_table"] == []
    assert "evidence_backed" not in response.json()["data"]
