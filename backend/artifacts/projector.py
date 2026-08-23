"""把 FSM 事务 Outbox 中的审批事件幂等投影为版本化产物。"""

from __future__ import annotations

from typing import Any

from common.workflow_contracts import get_stage_contract

from .models import Artifact, ArtifactKind, ArtifactStatus, ContextManifest
from .registry import ArtifactRegistry, ArtifactRegistryError


class ArtifactOutboxProjector:
    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    def project(self, event: dict[str, Any]) -> Artifact:
        """幂等投影单个事件；中途失败后可安全重试。"""
        event_id = str(event.get("event_id", ""))
        task_id = str(event.get("task_id", ""))
        stage_no = int(event.get("stage_no", 0) or 0)
        if not event_id or not task_id or stage_no not in range(1, 11):
            raise ArtifactRegistryError("非法产物 Outbox 事件")

        kind_value = str(
            event.get("kind") or get_stage_contract(stage_no).runtime_artifact_kind
        )
        kind = ArtifactKind(kind_value)
        dependencies = tuple(event.get("dependency_ids", ()) or ())
        if not dependencies and stage_no > 1:
            previous_contract = get_stage_contract(stage_no - 1)
            previous = self._registry.get_active(
                task_id=task_id,
                stage_no=stage_no - 1,
                kind=ArtifactKind(previous_contract.runtime_artifact_kind),
            )
            if previous is None:
                raise ArtifactRegistryError(
                    f"环{stage_no}投影前缺少环{stage_no - 1}有效批准产物"
                )
            dependencies = (previous.artifact_id,)

        artifact = self._registry.create_version(
            task_id=task_id,
            stage_no=stage_no,
            kind=kind,
            payload=dict(event.get("payload", {}) or {}),
            dependency_ids=dependencies,
            context_manifest=ContextManifest.from_dict(event.get("context_manifest")),
            source_event_id=event_id,
        )
        if artifact.status == ArtifactStatus.GENERATED:
            artifact = self._registry.submit_auto_gate(
                artifact.artifact_id,
                passed=bool(event.get("auto_gate_passed", True)),
                report=dict(event.get("gate_report", {}) or {}),
            )
        if artifact.status == ArtifactStatus.WAITING_APPROVAL:
            artifact = self._registry.decide(
                artifact.artifact_id,
                approved=bool(event.get("approved", True)),
                actor=str(event.get("actor", "author")),
                reason=str(event.get("reason", "")),
            )
        return artifact
