# -*- coding: utf-8 -*-
"""Project memory service mixin."""
from __future__ import annotations

from typing import Any, Dict, List

from common.aicoding.dto.result import Result

from artifacts import ArtifactKind, ArtifactStatus, ContextManifest
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from common.project_memory import validate_project_memory


class MemoryServiceMixin:
    """Versioned project memory CRUD with author approval."""

    def create_project_memory(
        self,
        task_id: str,
        value: Dict[str, Any],
        *,
        tenant_id: str = "",
        author_id: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        payload = self._without_autosave_controls(value)
        autosave = self._autosave_submission_draft(
            task_id,
            value,
            object_type="PROJECT_MEMORY_FORM",
            object_id="new",
            tenant_id=tenant_id,
            author_id=author_id,
        )
        self._assert_autosave_content_matches(autosave, payload)
        memory = validate_project_memory(payload)
        topic = self._artifacts.get_active(
            task_id=task_id,
            stage_no=1,
            kind=ArtifactKind.TOPIC_PROPOSAL,
        )
        dependencies = (topic.artifact_id,) if topic is not None else ()
        artifact = self._artifacts.create_version(
            task_id=task_id,
            stage_no=1,
            kind=ArtifactKind.PROJECT_MEMORY,
            payload=memory.model_dump(),
            dependency_ids=dependencies,
            context_manifest=ContextManifest(
                prompt_id="project_memory_authoring",
                prompt_version="v1",
                input_artifact_ids=dependencies,
            ),
        )
        artifact = self._artifacts.submit_auto_gate(
            artifact.artifact_id,
            passed=True,
            report={
                "schema_validation": "passed",
                "research_question_count": len(memory.research_questions),
                "decision_count": len(memory.decisions),
                "feedback_count": len(memory.supervisor_feedback),
                "terminology_count": len(memory.terminology),
                "requires_author_approval": True,
            },
        )
        data = self._artifact_dict(artifact)
        submitted_draft = self._complete_autosave_submission(
            autosave, artifact.artifact_id
        )
        if submitted_draft is not None:
            data["autosave_draft"] = submitted_draft.metadata()
        return Result.ok(
            data=data,
            msg="项目记忆新版本已生成，等待作者审批",
        )

    def review_project_memory(
        self,
        task_id: str,
        artifact_id: str,
        *,
        approved: bool,
        actor: str = "author",
        reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        artifact = self._artifacts.get(artifact_id)
        if artifact.task_id != task_id or artifact.kind != ArtifactKind.PROJECT_MEMORY:
            raise ValueError("当前任务中不存在该项目记忆版本")
        if artifact.status == ArtifactStatus.WAITING_APPROVAL:
            artifact = self._artifacts.decide(
                artifact_id,
                approved=approved,
                actor=actor,
                reason=reason,
            )
        elif artifact.status != ArtifactStatus.APPROVED or not approved:
            raise ValueError("该项目记忆版本当前状态不能审批")
        return Result.ok(data=self._artifact_dict(artifact), msg="项目记忆审批已记录")

    def list_project_memories(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[
                self._artifact_dict(artifact)
                for artifact in self._artifacts.list_task(task_id)
                if artifact.kind == ArtifactKind.PROJECT_MEMORY
            ],
            msg="项目记忆版本列表",
        )

    # ------------------------------------------------------------------
    # 持久化后台作业与预算
    # ------------------------------------------------------------------

