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
from writing.generator import SectionGeneration


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


class _SectionGenerator:
    def generate(self, context) -> SectionGeneration:
        evidence_ids = [
            evidence_id
            for claim in context.get("claims", [])
            for evidence_id in claim.get("supporting_evidence_ids", [])
        ]
        claim_text = " ".join(claim.get("text", "") for claim in context.get("claims", []))
        markers = " ".join(f"[{evidence_id}]" for evidence_id in evidence_ids)
        target = int(context.get("target_word_count", 300))
        content = f"{claim_text} {markers} " + ("可信分节正文" * ((target // 6) + 2))
        return SectionGeneration(
            title=context.get("title", ""),
            content=content,
            covered_claim_ids=[claim.get("claim_id", "") for claim in context.get("claims", [])],
            used_evidence_ids=evidence_ids,
            used_result_ids=[],
            generation_source="test-double",
        )


class _NeverCalledSectionGenerator:
    def generate(self, context):
        raise AssertionError("合同前置检查失败时不得调用模型")


class _ContractViolatingGenerator:
    def generate(self, context) -> SectionGeneration:
        evidence_ids = [
            evidence_id
            for claim in context.get("claims", [])
            for evidence_id in claim.get("supporting_evidence_ids", [])
        ]
        target = int(context.get("target_word_count", 300))
        content = (
            "未经核验的结论 "
            + " ".join(f"[{evidence_id}]" for evidence_id in evidence_ids)
            + (" 合同外正文" * (target + 1))
        )
        return SectionGeneration(
            title=context.get("title", ""),
            content=content,
            covered_claim_ids=[
                *[claim.get("claim_id", "") for claim in context.get("claims", [])],
                "CLM-OUTSIDE",
            ],
            used_evidence_ids=evidence_ids,
            used_result_ids=[],
            generation_source="test-double",
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
        section_generator=_SectionGenerator(),
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


def _approve_root_support(
    orchestration: MainOrchestration, task_id: str, argument_map: dict
):
    claim = orchestration.list_claims(
        task_id, artifact_id=argument_map["artifact_id"]
    ).data[0]
    source = orchestration.register_source(
        task_id,
        {
            "title": "Evidence Source",
            "doi": "10.1/evidence",
            "verification_status": "METADATA_VERIFIED",
        },
    ).data
    evidence = orchestration.add_evidence(
        task_id,
        {
            "source_id": source["source_id"],
            "quote": "Traceable evidence constraints reduced unsupported claims.",
            "page_start": 7,
        },
    ).data
    orchestration.review_evidence(task_id, evidence["evidence_id"], approved=True)
    orchestration.link_claim_evidence(
        task_id,
        claim["claim_id"],
        {"evidence_id": evidence["evidence_id"], "relation": "SUPPORTS"},
    )
    return claim, evidence


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


def test_outline_leaf_nodes_embed_hashed_section_contracts(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    argument_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    _, evidence = _approve_root_support(orchestration, task_id, argument_map)

    result = orchestration.run_ring5(task_id).data
    parent = next(item for item in result["chapters"] if item["level"] == 1)
    leaf = next(item for item in result["chapters"] if item["number"] == "1.1")
    contract = leaf["section_contract"]

    assert "section_contract" not in parent
    assert contract["schema_version"] == "m3"
    assert contract["allowed_claim_keys"] == ["ROOT"]
    assert contract["required_evidence_ids"] == [evidence["evidence_id"]]
    assert len(contract["canon_hash"]) == 64
    assert len(contract["contract_hash"]) == 64
    assert len(result["contract_hash"]) == 64

    orchestration.confirm_ring(task_id, 5)
    outline = next(
        item for item in orchestration.list_artifacts(task_id).data
        if item["kind"] == "OUTLINE"
    )
    assert outline["payload"]["contract_hash"] == result["contract_hash"]
    assert outline["context_manifest"]["canon_hash"] == result["canon_hash"]
    assert outline["context_manifest"]["contract_hash"] == result["contract_hash"]
    assert outline["gate_report"]["canon_hash"] == result["canon_hash"]
    assert outline["gate_report"]["contract_hash"] == result["contract_hash"]


def test_section_contract_preflight_blocks_before_model_call(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    argument_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    orchestration._section_generator = _NeverCalledSectionGenerator()  # noqa: SLF001

    with pytest.raises(Exception, match="缺少批准证据"):
        orchestration.generate_section_draft(task_id, {"section_id": "1.1"})


def test_numeric_section_contract_requires_verified_result_before_model(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    payload = _argument_map()
    payload["claims"][0]["claim_type"] = "NUMERIC"
    argument_map = orchestration.create_argument_map(task_id, payload).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    outline = orchestration.run_ring5(task_id).data
    numeric_contract = next(
        item["section_contract"]
        for item in outline["chapters"]
        if item["number"] == "1.1"
    )
    assert numeric_contract["requires_verified_results"] is True
    orchestration.confirm_ring(task_id, 5)
    orchestration._section_generator = _NeverCalledSectionGenerator()  # noqa: SLF001

    with pytest.raises(Exception, match="至少一个经用户核验的结果"):
        orchestration.generate_section_draft(task_id, {"section_id": "1.1"})


def test_section_contract_rejects_outside_claims_and_records_hashes(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    memory = orchestration.create_project_memory(
        task_id,
        {
            "forbidden_claims": ["未经核验的结论"],
            "version_note": "M3 contract",
        },
    ).data
    orchestration.review_project_memory(task_id, memory["artifact_id"], approved=True)
    argument_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    _approve_root_support(orchestration, task_id, argument_map)
    outline_result = orchestration.run_ring5(task_id).data
    orchestration.confirm_ring(task_id, 5)
    orchestration._section_generator = _ContractViolatingGenerator()  # noqa: SLF001

    generated = orchestration.generate_section_draft(
        task_id, {"section_id": "1.1"}
    )

    assert generated.is_ok is False
    assert generated.data["status"] == "AUTO_REJECTED"
    issues = generated.data["gate_report"]["issues"]
    assert any("合同外论断" in issue for issue in issues)
    assert any("禁写主张" in issue for issue in issues)
    assert generated.data["context_manifest"]["contract_hash"]
    assert generated.data["context_manifest"]["canon_hash"]
    assert (
        generated.data["gate_report"]["contract_hash"]
        == generated.data["context_manifest"]["contract_hash"]
    )
    leaf = next(
        item for item in outline_result["chapters"] if item["number"] == "1.1"
    )
    assert (
        generated.data["context_manifest"]["contract_hash"]
        == leaf["section_contract"]["contract_hash"]
    )


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
        task_id,
        {
            "title": "Evidence Source",
            "doi": "10.1/evidence",
            "verification_status": "METADATA_VERIFIED",
        },
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
    rejected_key = "section-revision:1.1"
    orchestration.save_autosave_draft(
        task_id,
        rejected_key,
        {
            "object_type": "SECTION_REVISION",
            "stage_no": 6,
            "base_artifact_id": first["section_draft_id"],
            "base_version": first["version"],
            "revision": 1,
            "content": {
                "content": "删除了全部证据标记的错误修订",
                "section_id": "1.1",
                "base_section_draft_id": first["section_draft_id"],
            },
        },
        tenant_id="default",
        author_id="author-a",
    )
    rejected_revision = orchestration.revise_section_draft(
        task_id,
        first["section_draft_id"],
        {
            "content": "删除了全部证据标记的错误修订",
            "autosave_draft_key": rejected_key,
            "autosave_revision": 1,
        },
        tenant_id="default",
        author_id="author-a",
    )
    assert rejected_revision.is_ok is False
    assert rejected_revision.data["status"] == "AUTO_REJECTED"
    assert orchestration._drafts.get(  # noqa: SLF001
        task_id, "author-a", rejected_key
    ).status == "ACTIVE"
    revised = orchestration.revise_section_draft(
        task_id,
        first["section_draft_id"],
        {"content": first["content"] + "\n\n作者补充了边界条件说明。"},
    ).data
    assert revised["version"] == 3
    assert revised["context_manifest"]["revision_parent_id"] == first["section_draft_id"]
    orchestration.review_section_draft(
        task_id, revised["section_draft_id"], approved=True
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
        revised["section_draft_id"], second["section_draft_id"]
    ]

    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    citation_audit = orchestration.run_ring8(task_id)
    assert citation_audit.is_ok
    assert citation_audit.data["citation_map"] == {evidence["evidence_id"]: 1}
    trust = citation_audit.data["trust_assessment"]
    assert trust["highest_tier"] == "EVIDENCE"
    assert trust["dimensions"]["evidence"]["status"] == "PASSED"
    assert trust["author_review"]["status"] == "PENDING"
    stored = orchestration._store.get(task_id).ring8
    assert f"[{evidence['evidence_id']}]" not in stored["rendered_content"]
    assert "[1]" in stored["rendered_content"]
    assert "# 参考文献" in stored["rendered_content"]
    orchestration.confirm_ring(task_id, 8)
    progress = orchestration.progress(task_id).data
    assert progress["trust_assessments"]["8"]["author_review"]["status"] == "APPROVED"


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


def test_section_revision_submits_matching_autosave_only_after_formal_success(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    argument_map = orchestration.create_argument_map(task_id, _argument_map()).data
    orchestration.review_argument_map(task_id, argument_map["artifact_id"], approved=True)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    parent = orchestration.generate_section_draft(
        task_id, {"section_id": "1.2"}
    ).data
    key = "section-revision:1.2"
    content = parent["content"] + "\n\n作者补充了局限条件。"
    saved = orchestration.save_autosave_draft(
        task_id,
        key,
        {
            "object_type": "SECTION_REVISION",
            "stage_no": 6,
            "base_artifact_id": parent["section_draft_id"],
            "base_version": parent["version"],
            "revision": 1,
            "content": {
                "content": content,
                "section_id": "1.2",
                "base_section_draft_id": parent["section_draft_id"],
            },
        },
        tenant_id="default",
        author_id="author-a",
    ).data
    assert saved["status"] == "ACTIVE"
    resume = orchestration.get_resume_summary(
        task_id, author_id="author-a"
    ).data
    assert resume["next_safe_action"]["type"] == "RESUME_DRAFT"
    assert resume["next_safe_action"]["draft_key"] == key

    revised = orchestration.revise_section_draft(
        task_id,
        parent["section_draft_id"],
        {
            "content": content,
            "autosave_draft_key": key,
            "autosave_revision": 1,
        },
        tenant_id="default",
        author_id="author-a",
    )
    assert revised.is_ok
    assert revised.data["autosave_draft"]["status"] == "SUBMITTED"
    assert revised.data["autosave_draft"]["revision"] == 2
    listed = orchestration.list_autosave_drafts(
        task_id, tenant_id="default", author_id="author-a"
    ).data["items"]
    assert listed[0]["status"] == "SUBMITTED"
    assert orchestration.get_resume_summary(
        task_id, author_id="author-a"
    ).data["autosaved_drafts"] == []

    next_content = revised.data["content"] + "\n\n尚未提交的下一轮修改。"
    orchestration.save_autosave_draft(
        task_id,
        key,
        {
            "object_type": "SECTION_REVISION",
            "stage_no": 6,
            "base_artifact_id": revised.data["section_draft_id"],
            "base_version": revised.data["version"],
            "revision": 3,
            "content": {
                "content": next_content,
                "section_id": "1.2",
                "base_section_draft_id": revised.data["section_draft_id"],
            },
        },
        tenant_id="default",
        author_id="author-a",
    )
    orchestration.revise_section_draft(
        task_id,
        revised.data["section_draft_id"],
        {"content": revised.data["content"] + "\n\n另一页面的正式修改。"},
    )
    listed_after_change = orchestration.list_autosave_drafts(
        task_id, tenant_id="default", author_id="author-a"
    ).data["items"]
    current = next(item for item in listed_after_change if item["draft_key"] == key)
    assert current["status"] == "STALE"


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
