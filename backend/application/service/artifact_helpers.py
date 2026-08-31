# -*- coding: utf-8 -*-
"""产物与FSM共享工具方法（从 uc_main_orchestration.py 拆出的 mixin）。

ArtifactHelpersMixin 依赖宿主类提供：
    self._fsm                — FsmOrchestrator 实例
    self._artifacts          — ArtifactRegistry 实例
    self._artifact_projector — ArtifactOutboxProjector 实例
    self._require(task_id)   — 身份校验方法
    self._register_literature_sources(...) — 来自 EvidenceServiceMixin
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from common.aicoding.enums.phase_state import PhaseState
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from common.workflow_contracts import get_stage_contract

from artifacts import ArtifactKind, ArtifactStatus
from research import ResearchMethod

from application.service.task_store import TaskRecord

logger = logging.getLogger("thesis.uc")


class ArtifactHelpersMixin:
    """产物序列化、Outbox投影与环执行前置守卫。"""

    @staticmethod
    def _cross_reference_display(target: str) -> str:
        upper = target.upper()
        if upper.startswith("TABLE-"):
            return "表" + target[6:]
        if upper.startswith("FIGURE-"):
            return "图" + target[7:]
        return target

    @staticmethod
    def _method_requires_execution(payload: Dict[str, Any]) -> bool:
        return str(payload.get("method", "")) in {
            ResearchMethod.QUANTITATIVE.value,
            ResearchMethod.QUALITATIVE.value,
            ResearchMethod.MIXED.value,
            ResearchMethod.SYSTEM_BUILD.value,
        }

    @staticmethod
    def _artifact_dict(artifact) -> Dict[str, Any]:
        return {
            "artifact_id": artifact.artifact_id,
            "task_id": artifact.task_id,
            "stage_no": artifact.stage_no,
            "kind": artifact.kind.value,
            "version": artifact.version,
            "status": artifact.status.value,
            "payload": artifact.payload,
            "dependency_ids": list(artifact.dependency_ids),
            "gate_report": artifact.gate_report,
            "stale_reason": artifact.stale_reason,
            "created_at": artifact.created_at,
            "updated_at": artifact.updated_at,
        }

    def _project_pending_artifacts(self, task_id: str) -> list[str]:
        """重放 FSM Outbox；投影失败不丢事件，由下次调用继续恢复。"""
        state = self._fsm.get_task(task_id)
        outbox = state.aux_artifacts.get("artifact_outbox", [])
        if not isinstance(outbox, list):
            return ["artifact_outbox 状态损坏"]
        issues: list[str] = []
        for event in outbox:
            if not isinstance(event, dict) or event.get("projection_status") == "PROJECTED":
                continue
            event_id = str(event.get("event_id", ""))
            try:
                artifact = self._artifact_projector.project(event)
                if artifact.stage_no == 3 and artifact.status == ArtifactStatus.APPROVED:
                    self._register_literature_sources(
                        task_id=task_id,
                        payload=artifact.payload,
                        artifact_id=artifact.artifact_id,
                        source_event_id=event_id,
                    )
                self._fsm.mark_artifact_event_projected(
                    task_id,
                    event_id,
                    artifact.artifact_id,
                )
            except Exception as exc:  # noqa: BLE001 - Outbox 保留供下次重试
                logger.warning("产物 Outbox 投影失败 %s: %s", event_id, exc)
                issues.append(f"{event_id}: {exc}")
        return issues

    def _require_current_ring(self, task_id: str, ring_no: int) -> TaskRecord:
        """要求任务正处于指定环且允许执行，阻止跨环调用。"""
        rec = self._require(task_id)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != ring_no:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg=f"当前应执行环{state.current_ring_no}，不能执行环{ring_no}",
            )
        if state.phase_state == PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg=f"环{ring_no}已有待确认产物，请先确认或拒绝",
            )
        if state.phase_state == PhaseState.PASSED:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, msg="任务已经完成")
        if ring_no > 1:
            previous = get_stage_contract(ring_no - 1)
            active_previous = self._artifacts.get_active(
                task_id=task_id,
                stage_no=ring_no - 1,
                kind=ArtifactKind(previous.runtime_artifact_kind),
            )
            if active_previous is None:
                raise BizException(
                    ErrorCode.FSM_INVALID_TRANSITION,
                    msg=f"环{ring_no - 1}有效批准产物缺失或已过期，不能执行环{ring_no}",
                    detail={"required_artifact": previous.runtime_artifact_kind},
                )
        return rec
