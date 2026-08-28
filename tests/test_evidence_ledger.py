"""来源、摘录、论断与证据链接的完整性测试。"""

from __future__ import annotations

import json

import pytest

from artifacts import ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from evidence import (
    ClaimType,
    EvidenceLedger,
    EvidenceLedgerError,
    EvidenceRelation,
    SourceVerificationStatus,
)
from executor.base import ExecResult


def _source(ledger: EvidenceLedger, task_id: str = "task-1"):
    return ledger.register_source(
        task_id=task_id,
        title="Reliable Agent Workflows",
        authors=["Ada Lovelace"],
        year=2025,
        doi="https://doi.org/10.1000/XYZ.1",
        verification_status=SourceVerificationStatus.METADATA_VERIFIED,
    )


def test_source_registration_is_idempotent_by_normalized_doi():
    ledger = EvidenceLedger()
    first = _source(ledger)
    second = ledger.register_source(
        task_id="task-1",
        title="A better title from a verified provider",
        doi="doi:10.1000/xyz.1",
        provider="crossref",
        verification_status=SourceVerificationStatus.CONTENT_VERIFIED,
    )

    assert first.source_id == second.source_id
    assert len(ledger.list_sources("task-1")) == 1
    assert second.title == "A better title from a verified provider"
    assert second.verification_status == SourceVerificationStatus.CONTENT_VERIFIED


def test_evidence_ledger_enforces_task_isolation():
    ledger = EvidenceLedger()
    source = _source(ledger, "task-a")
    other = _source(ledger, "task-b")
    assert other.source_id != source.source_id

    with pytest.raises(EvidenceLedgerError, match="当前任务"):
        ledger.get_source("task-b", source.source_id)
    with pytest.raises(EvidenceLedgerError, match="当前任务"):
        ledger.add_excerpt(
            task_id="task-b", source_id=source.source_id, quote="isolated", page_start=1
        )


def test_excerpt_requires_locator_and_author_review_before_linking():
    ledger = EvidenceLedger()
    source = _source(ledger)
    with pytest.raises(EvidenceLedgerError, match="定位"):
        ledger.add_excerpt(task_id="task-1", source_id=source.source_id, quote="No locator")

    excerpt = ledger.add_excerpt(
        task_id="task-1",
        source_id=source.source_id,
        quote="The workflow retained provenance for every transition.",
        page_start=12,
        section="3.2",
    )
    claim = ledger.add_claim(
        task_id="task-1",
        text="该工作流保留了全链路来源信息。",
        claim_type=ClaimType.FACTUAL,
    )
    with pytest.raises(EvidenceLedgerError, match="作者批准"):
        ledger.link_evidence(
            task_id="task-1",
            claim_id=claim.claim_id,
            evidence_id=excerpt.evidence_id,
            relation=EvidenceRelation.SUPPORTS,
        )

    approved = ledger.review_excerpt(
        "task-1", excerpt.evidence_id, approved=True, actor="author"
    )
    # 批准摘录是人工项目决策，不能伪装成系统已逐字核对全文。
    assert ledger.get_source(
        "task-1", source.source_id
    ).verification_status == SourceVerificationStatus.METADATA_VERIFIED
    link = ledger.link_evidence(
        task_id="task-1",
        claim_id=claim.claim_id,
        evidence_id=approved.evidence_id,
        relation=EvidenceRelation.SUPPORTS,
    )
    assert link.evidence_id == excerpt.evidence_id


def test_audit_blocks_unsupported_and_disputed_claims():
    ledger = EvidenceLedger()
    source = _source(ledger)
    support = ledger.add_excerpt(
        task_id="task-1", source_id=source.source_id, quote="support", page_start=2
    )
    contradiction = ledger.add_excerpt(
        task_id="task-1", source_id=source.source_id, quote="contradiction", page_start=3
    )
    ledger.review_excerpt("task-1", support.evidence_id, approved=True)
    ledger.review_excerpt("task-1", contradiction.evidence_id, approved=True)
    supported_claim = ledger.add_claim(task_id="task-1", text="supported", artifact_id="ART-1")
    unsupported_claim = ledger.add_claim(task_id="task-1", text="unsupported", artifact_id="ART-1")
    disputed_claim = ledger.add_claim(task_id="task-1", text="disputed", artifact_id="ART-1")
    ledger.link_evidence(
        task_id="task-1", claim_id=supported_claim.claim_id,
        evidence_id=support.evidence_id, relation=EvidenceRelation.SUPPORTS,
    )
    ledger.link_evidence(
        task_id="task-1", claim_id=disputed_claim.claim_id,
        evidence_id=support.evidence_id, relation=EvidenceRelation.SUPPORTS,
    )
    ledger.link_evidence(
        task_id="task-1", claim_id=disputed_claim.claim_id,
        evidence_id=contradiction.evidence_id, relation=EvidenceRelation.CONTRADICTS,
    )

    audit = ledger.audit("task-1", artifact_id="ART-1")
    assert audit["supported_count"] == 1
    assert audit["unsupported_count"] == 1
    assert audit["disputed_count"] == 1
    assert audit["can_publish"] is False
    assert set(audit["blocking_claim_ids"]) == {
        unsupported_claim.claim_id,
        disputed_claim.claim_id,
    }


def test_rejected_evidence_no_longer_satisfies_a_claim():
    ledger = EvidenceLedger()
    source = _source(ledger)
    excerpt = ledger.add_excerpt(
        task_id="task-1", source_id=source.source_id, quote="temporary support", page_start=9
    )
    ledger.review_excerpt("task-1", excerpt.evidence_id, approved=True)
    claim = ledger.add_claim(task_id="task-1", text="claim")
    ledger.link_evidence(
        task_id="task-1", claim_id=claim.claim_id,
        evidence_id=excerpt.evidence_id, relation=EvidenceRelation.SUPPORTS,
    )
    assert ledger.audit("task-1")["can_publish"] is True

    ledger.review_excerpt(
        "task-1", excerpt.evidence_id, approved=False, reason="页码与原文不符"
    )
    audit = ledger.audit("task-1")
    assert audit["can_publish"] is False
    assert audit["unsupported_count"] == 1
    assert audit["claims"][0]["invalid_evidence_ids"] == [excerpt.evidence_id]


class _ThreeRingExecutor:
    def __init__(self, ring_no: int) -> None:
        self.ring_no = ring_no

    def execute(self, ctx) -> ExecResult:
        if self.ring_no == 1:
            payload = {
                "candidates": [{"title": "证据驱动的论文智能体"}],
                "recommendation": "推荐",
            }
        elif self.ring_no == 2:
            payload = {
                "novelty_level": "HIGH",
                "similar_count": 0,
                "recommendation": "通过",
            }
        else:
            payload = {
                "theme": "证据驱动的论文智能体",
                "items": [
                    {
                        "title": "Auditable Academic Agents",
                        "authors": ["Grace Hopper"],
                        "year": 2025,
                        "venue": "Journal of Agent Systems",
                        "doi": "10.5555/agent.2025.1",
                        "abstract": "An auditable architecture.",
                        "category": "方法",
                        "reliability": "matched",
                        "gbt7714": "HOPPER G. Auditable Academic Agents[J]. 2025.",
                        "urls": ["https://doi.org/10.5555/agent.2025.1"],
                    }
                ],
                "total": 1,
            }
        return ExecResult(
            output=json.dumps(payload, ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


def _orchestration(monkeypatch) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _ThreeRingExecutor(int(ring_no)),
    )
    return MainOrchestration(
        artifact_registry=ArtifactRegistry(), evidence_ledger=EvidenceLedger()
    )


def test_approved_ring3_literature_is_registered_as_project_source(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "论文智能体", Degree.MASTER, "计算机科学", session_id="evidence-ring3"
    ).data["task_id"]
    for ring_no, run in (
        (1, orchestration.run_ring1),
        (2, orchestration.run_ring2),
        (3, orchestration.run_ring3),
    ):
        run(task_id)
        orchestration.confirm_ring(task_id, ring_no)

    sources = orchestration.list_sources(task_id).data
    assert len(sources) == 1
    assert sources[0]["doi"] == "10.5555/agent.2025.1"
    assert sources[0]["provider"] == "ring3"
    assert sources[0]["verification_status"] == "METADATA_VERIFIED"
    assert sources[0]["metadata"]["artifact_id"].startswith("ART-")


def test_evidence_workflow_is_exposed_by_console_api(monkeypatch):
    from application.main import build_app
    from fastapi.testclient import TestClient

    app = build_app(orchestration=_orchestration(monkeypatch))
    client = TestClient(app)
    created = client.post(
        "/api/v1/console/tasks",
        json={
            "title": "证据API测试",
            "degree": "MASTER",
            "subject_field": "计算机科学",
            "session_id": "evidence-api",
        },
    ).json()
    task_id = created["data"]["task_id"]
    base = f"/api/v1/console/tasks/{task_id}"
    query = "?session_id=evidence-api"
    source = client.post(
        f"{base}/sources{query}",
        json={"title": "API Source", "year": 2025, "doi": "10.1/api"},
    ).json()["data"]
    evidence = client.post(
        f"{base}/evidence{query}",
        json={"source_id": source["source_id"], "quote": "API evidence", "page_start": 8},
    ).json()["data"]
    client.post(
        f"{base}/evidence/{evidence['evidence_id']}/review{query}",
        json={"approved": True},
    )
    claim = client.post(
        f"{base}/claims{query}", json={"text": "API claim", "claim_type": "FACTUAL"}
    ).json()["data"]
    linked = client.post(
        f"{base}/claims/{claim['claim_id']}/links{query}",
        json={"evidence_id": evidence["evidence_id"], "relation": "SUPPORTS"},
    ).json()
    audit = client.get(f"{base}/evidence-audit{query}").json()

    assert linked["code"] == 0
    assert audit["data"]["can_publish"] is True
    assert audit["data"]["supported_count"] == 1
