"""分节版本、证据约束、逐节审批与环6汇编测试。"""

from __future__ import annotations

import json

import pytest

from artifacts import ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from evidence import EvidenceLedger
from executor.base import ExecResult
from research import ResearchExecutionRegistry
from writing import SectionDraftRegistry, SectionDraftStatus


class _Executor:
    def __init__(self, ring_no: int) -> None:
        self.ring_no = ring_no

    def execute(self, ctx) -> ExecResult:
        if self.ring_no == 7:
            draft = json.loads(ctx.draft)
            return ExecResult(
                output=json.dumps(
                    {"chapters": draft.get("chapters", []), "total_words": 20},
                    ensure_ascii=False,
                ),
                accept=True,
                evidence={"source": "test-double"},
            )
        payloads = {
            1: {"candidates": [{"title": "分节可信写作"}], "recommendation": "推荐"},
            2: {"novelty_level": "HIGH", "similar_count": 0, "recommendation": "通过"},
            3: {"items": [{"title": "Section Writing", "doi": "10.1/section"}], "summary": "1条"},
            4: {"verdict": "顺", "overlap_count": 0, "recommendation": "通过"},
            5: {
                "theme": "分节可信写作",
                "chapters": [
                    {"level": 1, "number": "1", "title": "实验分析"},
                    {"level": 2, "number": "1.1", "title": "证据约束"},
                    {"level": 2, "number": "1.2", "title": "局限讨论"},
                ],
                "summary": "大纲",
            },
        }
        return ExecResult(
            output=json.dumps(payloads[self.ring_no], ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


def _orchestration(monkeypatch) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Executor(int(ring_no)),
    )
    return MainOrchestration(
        artifact_registry=ArtifactRegistry(),
        evidence_ledger=EvidenceLedger(),
        research_registry=ResearchExecutionRegistry(),
        section_registry=SectionDraftRegistry(),
    )


def _advance_to_ring5(orchestration: MainOrchestration) -> str:
    task_id = orchestration.create_task(
        "分节写作", Degree.MASTER, "计算机科学", session_id="sections"
    ).data["task_id"]
    for ring_no, runner in (
        (1, orchestration.run_ring1),
        (2, orchestration.run_ring2),
        (3, orchestration.run_ring3),
        (4, orchestration.run_ring4),
    ):
        runner(task_id)
        orchestration.confirm_ring(task_id, ring_no)
    return task_id


def _argument_map() -> dict:
    return {
        "title": "分节论证图",
        "research_questions": ["证据约束是否有效？"],
        "claims": [
            {
                "claim_key": "ROOT",
                "text": "可定位证据约束能够减少无依据论断",
                "section_id": "1.1",
                "claim_type": "FACTUAL",
                "role": "THESIS",
                "parent_keys": [],
                "evidence_requirements": ["原文证据"],
            }
        ],
    }


def test_section_registry_versions_each_section_independently():
    registry = SectionDraftRegistry()
    first = registry.create_version(
        task_id="task", section_id="1.1", title="A", content="v1"
    )
    first = registry.submit_auto_gate("task", first.section_draft_id, passed=True)
    registry.decide("task", first.section_draft_id, approved=True)
    second = registry.create_version(
        task_id="task", section_id="1.1", title="A", content="v2"
    )
    second = registry.submit_auto_gate("task", second.section_draft_id, passed=True)
    registry.decide("task", second.section_draft_id, approved=True)
    other = registry.create_version(
        task_id="task", section_id="1.2", title="B", content="other"
    )
    assert second.version == 2
    assert other.version == 1
    assert registry.get("task", first.section_draft_id).status == SectionDraftStatus.SUPERSEDED
    assert registry.list_approvals("task", second.section_draft_id)[0]["actor"] == "author"


def test_section_generation_requires_supported_claims_and_assembles(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    argument_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)

    with pytest.raises(Exception, match="缺少批准证据"):
        orchestration.generate_section_draft(task_id, {"section_id": "1.1"})

    claim = orchestration.list_claims(
        task_id, artifact_id=argument_map["artifact_id"]
    ).data[0]
    source = orchestration.register_source(
        task_id, {"title": "Evidence Source", "doi": "10.1/evidence"}
    ).data
    evidence = orchestration.add_evidence(
        task_id,
        {
            "source_id": source["source_id"],
            "quote": "Traceable evidence constraints reduced unsupported claims.",
            "page_start": 7,
        },
    ).data
    orchestration.review_evidence(
        task_id, evidence["evidence_id"], approved=True
    )
    orchestration.link_claim_evidence(
        task_id,
        claim["claim_id"],
        {"evidence_id": evidence["evidence_id"], "relation": "SUPPORTS"},
    )

    first = orchestration.generate_section_draft(task_id, {"section_id": "1.1"}).data
    second = orchestration.generate_section_draft(task_id, {"section_id": "1.2"}).data
    assert first["status"] == "WAITING_APPROVAL"
    assert first["evidence_ids"] == [evidence["evidence_id"]]
    orchestration.review_section_draft(
        task_id, first["section_draft_id"], approved=True
    )
    orchestration.review_section_draft(
        task_id, second["section_draft_id"], approved=True
    )
    assert orchestration.audit_section_drafts(task_id).data["can_assemble"] is True

    assembled = orchestration.assemble_section_drafts(task_id)
    assert assembled.data["section_count"] == 2
    assert assembled.data["used_evidence_ids"] == [evidence["evidence_id"]]
    assert orchestration.progress(task_id).data["phase_state"] == "WAITING_APPROVAL"
    orchestration.confirm_ring(task_id, 6)
    artifacts = orchestration.list_artifacts(task_id).data
    draft = next(item for item in artifacts if item["kind"] == "SECTION_DRAFT")
    assert draft["payload"]["section_draft_ids"] == [
        first["section_draft_id"], second["section_draft_id"]
    ]

    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    citation_audit = orchestration.run_ring8(task_id)
    assert citation_audit.is_ok
    assert citation_audit.data["citation_map"] == {evidence["evidence_id"]: 1}
    stored = orchestration._store.get(task_id).ring8
    assert f"[{evidence['evidence_id']}]" not in stored["rendered_content"]
    assert "[1]" in stored["rendered_content"]
    assert "# 参考文献" in stored["rendered_content"]


def test_upstream_argument_revision_stales_approved_sections(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    first_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, first_map["artifact_id"], approved=True)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    section = orchestration.generate_section_draft(task_id, {"section_id": "1.2"}).data
    orchestration.review_section_draft(
        task_id, section["section_draft_id"], approved=True
    )

    orchestration._fsm.rollback(task_id, 5)
    revised = _argument_map()
    revised["claims"][0]["text"] = "修订后的核心论断"
    second_map = orchestration.create_argument_map(task_id, revised).data
    orchestration.review_argument_map(task_id, second_map["artifact_id"], approved=True)
    listed = orchestration.list_section_drafts(task_id).data
    assert listed[0]["status"] == "STALE"
    assert listed[0]["stale_reason"].startswith("上游产物已失效: ART-")


def test_section_writing_endpoints_are_available(monkeypatch):
    from application.main import build_app
    from fastapi.testclient import TestClient

    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    client = TestClient(build_app(orchestration=orchestration))
    query = "?session_id=sections"
    generated = client.post(
        f"/api/v1/console/tasks/{task_id}/writing/sections/generate{query}",
        json={"section_id": "1.1"},
    ).json()
    assert generated["code"] == 0
    draft_id = generated["data"]["section_draft_id"]
    reviewed = client.post(
        f"/api/v1/console/tasks/{task_id}/writing/sections/{draft_id}/review{query}",
        json={"approved": True},
    ).json()
    assert reviewed["data"]["status"] == "APPROVED"
    assert reviewed["data"]["approvals"][0]["decision"] == "APPROVE"
