"""版本化产物、审批和依赖失效测试。"""

from __future__ import annotations

import pytest

from artifacts import (
    ArtifactKind,
    ArtifactOutboxProjector,
    ArtifactRegistry,
    ArtifactRegistryError,
    ArtifactStatus,
    ContextManifest,
)


def _approve(registry: ArtifactRegistry, artifact_id: str):
    registry.submit_auto_gate(artifact_id, passed=True, report={"schema": "passed"})
    return registry.decide(artifact_id, approved=True, actor="author")


def test_artifact_requires_auto_gate_before_user_approval(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    generated = registry.create_version(
        task_id="TASK-1",
        stage_no=1,
        kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "大模型教育应用"},
    )
    assert generated.status == ArtifactStatus.GENERATED
    with pytest.raises(ArtifactRegistryError):
        registry.decide(generated.artifact_id, approved=True)

    waiting = registry.submit_auto_gate(
        generated.artifact_id,
        passed=True,
        report={"required_fields": "passed"},
    )
    assert waiting.status == ArtifactStatus.WAITING_APPROVAL
    approved = registry.decide(waiting.artifact_id, approved=True)
    assert approved.status == ArtifactStatus.APPROVED
    assert registry.list_approvals(approved.artifact_id)[0]["decision"] == "APPROVE"


def test_context_manifest_and_dependency_are_persisted(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    brief = registry.create_version(
        task_id="TASK-1",
        stage_no=1,
        kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "RAG"},
    )
    _approve(registry, brief.artifact_id)
    proposal = registry.create_version(
        task_id="TASK-1",
        stage_no=2,
        kind=ArtifactKind.TOPIC_PROPOSAL,
        payload={"title": "面向学术写作的RAG证据链研究"},
        dependency_ids=[brief.artifact_id],
        context_manifest=ContextManifest(
            prompt_id="topic-proposal",
            prompt_version="1.0.0",
            model="test-model",
            input_artifact_ids=(brief.artifact_id,),
            token_budget=8000,
        ),
    )
    restored = registry.get(proposal.artifact_id)
    assert restored.dependency_ids == (brief.artifact_id,)
    assert restored.context_manifest.prompt_version == "1.0.0"
    assert restored.context_manifest.input_artifact_ids == (brief.artifact_id,)


def test_rejected_revision_keeps_previous_version_active(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    first = registry.create_version(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "方向A"},
    )
    first = _approve(registry, first.artifact_id)
    second = registry.create_version(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "方向B"},
    )
    registry.submit_auto_gate(second.artifact_id, passed=True)
    registry.decide(second.artifact_id, approved=False, reason="作者保留方向A")
    active = registry.get_active(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF
    )
    assert active is not None
    assert active.artifact_id == first.artifact_id
    assert registry.get(second.artifact_id).status == ArtifactStatus.REJECTED


def test_approved_revision_recursively_invalidates_downstream(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    brief_v1 = registry.create_version(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "方向A"},
    )
    _approve(registry, brief_v1.artifact_id)
    proposal = registry.create_version(
        task_id="TASK-1", stage_no=2, kind=ArtifactKind.TOPIC_PROPOSAL,
        payload={"title": "题目A"}, dependency_ids=[brief_v1.artifact_id],
    )
    _approve(registry, proposal.artifact_id)
    outline = registry.create_version(
        task_id="TASK-1", stage_no=5, kind=ArtifactKind.OUTLINE,
        payload={"sections": ["绪论"]}, dependency_ids=[proposal.artifact_id],
    )
    _approve(registry, outline.artifact_id)

    brief_v2 = registry.create_version(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "方向B"},
    )
    _approve(registry, brief_v2.artifact_id)

    assert registry.get(brief_v1.artifact_id).status == ArtifactStatus.SUPERSEDED
    assert registry.get(proposal.artifact_id).status == ArtifactStatus.STALE
    assert registry.get(outline.artifact_id).status == ArtifactStatus.STALE
    assert registry.get_active(
        task_id="TASK-1", stage_no=5, kind=ArtifactKind.OUTLINE
    ) is None


def test_dependency_must_be_approved_and_in_same_task(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    unapproved = registry.create_version(
        task_id="TASK-1", stage_no=1, kind=ArtifactKind.PROJECT_BRIEF,
        payload={"direction": "A"},
    )
    with pytest.raises(ArtifactRegistryError, match="只能依赖已批准"):
        registry.create_version(
            task_id="TASK-1", stage_no=2, kind=ArtifactKind.TOPIC_PROPOSAL,
            payload={"title": "A"}, dependency_ids=[unapproved.artifact_id],
        )
    _approve(registry, unapproved.artifact_id)
    with pytest.raises(ArtifactRegistryError, match="跨论文任务"):
        registry.create_version(
            task_id="TASK-2", stage_no=2, kind=ArtifactKind.TOPIC_PROPOSAL,
            payload={"title": "B"}, dependency_ids=[unapproved.artifact_id],
        )


def test_outbox_projection_is_idempotent(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts.db")
    projector = ArtifactOutboxProjector(registry)
    event = {
        "event_id": "EVT-1",
        "task_id": "TASK-1",
        "stage_no": 1,
        "kind": "TOPIC_PROPOSAL",
        "payload": {"title": "可信题目"},
        "auto_gate_passed": True,
        "approved": True,
        "actor": "author",
    }
    first = projector.project(event)
    second = projector.project(event)
    assert first.artifact_id == second.artifact_id
    assert second.status == ArtifactStatus.APPROVED
    assert len(registry.list_task("TASK-1")) == 1
