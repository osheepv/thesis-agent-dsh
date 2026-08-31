# -*- coding: utf-8 -*-
"""Workspace and autosave draft service mixin."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from common.aicoding.dto.result import Result
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from writing import (
    AutosaveDraftError,
    AutosaveDraftRevisionConflict,
)
from common.resume import (
    WorkspaceState,
    WorkspaceRevisionConflict,
    read_revision,
    validate_workspace_state,
    workspace_content,
)


class WorkspaceServiceMixin:
    """Workspace position persistence, autosave draft CRUD and staleness refresh."""

    def save_workspace_state(
        self,
        workspace_key: str,
        value: Dict[str, Any],
        *,
        tenant_id: str = "",
    ) -> Result[Dict[str, Any]]:
        state = validate_workspace_state(value)
        if state.last_task_id:
            rec = self._require(state.last_task_id)
            if tenant_id and rec.tenant_id != tenant_id:
                raise PermissionError("无权将工作区指向其他租户任务")
        try:
            stored = self._store.put_workspace(
                workspace_key,
                state.model_dump(exclude={"updated_at"}),
            )
        except WorkspaceRevisionConflict as exc:
            # 工作区冲突只影响 UI 位置，绝不上升为论文业务失败，也不覆盖已保存状态。
            return Result.fail(
                code=ErrorCode.STATE_CONFLICT.value,
                msg=str(exc),
                data={
                    "conflict": True,
                    "current_revision": exc.current_revision,
                    "incoming_revision": exc.incoming_revision,
                    "workspace": self.get_workspace_state(
                        workspace_key, tenant_id=tenant_id
                    ).data,
                },
            )
        return Result.ok(data=stored, msg="工作区位置已保存")

    # ------------------------------------------------------------------
    # 作者私有自动草稿（未提交工作副本，不推进流程）
    # ------------------------------------------------------------------
    def list_autosave_drafts(
        self, task_id: str, *, tenant_id: str = "", author_id: str = ""
    ) -> Result[Dict[str, Any]]:
        """列出当前作者的草稿元数据（含墓碑），绝不返回正文内容。"""
        rec = self._require(task_id)
        if tenant_id and rec.tenant_id != tenant_id:
            raise PermissionError("无权查看其他租户的草稿")
        self._refresh_autosave_staleness(
            task_id, author_id or "default"
        )
        drafts = self._drafts.list_task(
            task_id, author_id or "default", include_submitted=True
        )
        return Result.ok(
            data={"items": [draft.metadata() for draft in drafts]},
            msg="自动草稿列表",
        )

    def get_autosave_draft(
        self, task_id: str, draft_key: str, *, tenant_id: str = "", author_id: str = ""
    ) -> Result[Dict[str, Any]]:
        """只有草稿所有者在明确请求单个草稿时返回 content_json。"""
        rec = self._require(task_id)
        if tenant_id and rec.tenant_id != tenant_id:
            raise PermissionError("无权查看其他租户的草稿")
        self._refresh_autosave_staleness(
            task_id, author_id or "default"
        )
        draft = self._drafts.get(task_id, author_id or "default", draft_key)
        if draft is None:
            return Result.ok(data=None, msg="草稿不存在")
        return Result.ok(data=draft.to_dict(include_content=True), msg="自动草稿详情")

    def save_autosave_draft(
        self,
        task_id: str,
        draft_key: str,
        value: Dict[str, Any],
        *,
        tenant_id: str = "",
        author_id: str = "",
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        if tenant_id and rec.tenant_id != tenant_id:
            raise PermissionError("无权在其他租户任务中保存草稿")
        try:
            draft = self._drafts.save(
                task_id=task_id,
                tenant_id=rec.tenant_id,
                author_id=author_id or "default",
                object_type=str(value.get("object_type", "")),
                draft_key=draft_key,
                content=value.get("content"),
                stage_no=value.get("stage_no", 0),
                base_artifact_id=value.get("base_artifact_id", ""),
                base_version=value.get("base_version", 0),
                revision=value.get("revision", 0),
            )
        except AutosaveDraftRevisionConflict as exc:
            # 冲突只影响未提交草稿，不改变任何正式论文状态。
            return Result.fail(
                code=ErrorCode.STATE_CONFLICT.value,
                msg=str(exc),
                data={
                    "conflict": True,
                    "current_revision": exc.current_revision,
                    "incoming_revision": exc.incoming_revision,
                    "remote": exc.remote.metadata(),
                },
            )
        return Result.ok(data=draft.metadata(), msg="草稿已保存")

    def discard_autosave_draft(
        self,
        task_id: str,
        draft_key: str,
        *,
        revision: Any,
        tenant_id: str = "",
        author_id: str = "",
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        if tenant_id and rec.tenant_id != tenant_id:
            raise PermissionError("无权丢弃其他租户的草稿")
        if revision is None:
            raise AutosaveDraftError("丢弃草稿必须携带当前revision")
        try:
            removed = self._drafts.discard(
                task_id,
                author_id or "default",
                draft_key,
                revision=int(revision),
            )
        except AutosaveDraftRevisionConflict as exc:
            return Result.fail(
                code=ErrorCode.STATE_CONFLICT.value,
                msg=str(exc),
                data={
                    "conflict": True,
                    "current_revision": exc.current_revision,
                    "incoming_revision": exc.incoming_revision,
                    "remote": exc.remote.metadata(),
                },
            )
        if removed is None:
            return Result.ok(data={"discarded": False}, msg="草稿不存在")
        return Result.ok(
            data={"discarded": True, "draft": removed.metadata()},
            msg="草稿已丢弃",
        )

    def _autosave_submission_draft(
        self,
        task_id: str,
        value: Dict[str, Any],
        *,
        object_type: str,
        object_id: str,
        tenant_id: str = "",
        author_id: str = "",
    ):
        """核验明确提交所引用的作者私有草稿；旧客户端未传草稿键时保持兼容。"""
        draft_key = str(value.get("autosave_draft_key", "")).strip()
        if not draft_key:
            return None
        rec = self._require(task_id)
        if tenant_id and rec.tenant_id != tenant_id:
            raise PermissionError("无权提交其他租户的草稿")
        draft = self._drafts.get(task_id, author_id or "default", draft_key)
        if draft is None:
            raise AutosaveDraftError("要提交的自动草稿不存在")
        if draft.object_type != object_type or draft.object_id != object_id:
            raise AutosaveDraftError("自动草稿对象与正式提交目标不匹配")
        if draft.status == "STALE":
            raise AutosaveDraftError("过期草稿必须基于最新正式版本重建后才能提交")
        if draft.status != "ACTIVE":
            raise AutosaveDraftError(f"当前草稿状态不能提交: {draft.status}")
        try:
            incoming_revision = int(value.get("autosave_revision"))
        except (TypeError, ValueError) as exc:
            raise AutosaveDraftError("正式提交必须携带当前autosave_revision") from exc
        if incoming_revision != draft.revision:
            raise AutosaveDraftRevisionConflict(
                draft, incoming_revision, "正式提交基于旧版本"
            )
        return draft

    def _complete_autosave_submission(self, draft, submitted_to_id: str):
        if draft is None:
            return None
        return self._drafts.mark_submitted(
            draft.task_id,
            draft.author_id,
            draft.draft_key,
            submitted_to_id=submitted_to_id,
            revision=draft.revision,
        )

    @staticmethod
    def _without_autosave_controls(value: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(value)
        payload.pop("autosave_draft_key", None)
        payload.pop("autosave_revision", None)
        return payload

    @staticmethod
    def _assert_autosave_content_matches(draft, payload: Dict[str, Any]) -> None:
        if draft is not None and draft.content_json != payload:
            raise AutosaveDraftError(
                "正式提交内容与指定自动草稿revision不一致"
            )

    def _refresh_autosave_staleness(self, task_id: str, author_id: str) -> None:
        """按当前正式基线标记作者草稿过期；保留内容，不静默重放。"""
        state = self._fsm.get_task(task_id)
        section_drafts = self._sections.list_task(task_id)
        latest_by_section: Dict[str, Any] = {}
        for section in section_drafts:
            current = latest_by_section.get(section.section_id)
            if current is None or section.version > current.version:
                latest_by_section[section.section_id] = section
        for draft in self._drafts.list_task(task_id, author_id):
            if draft.status != "ACTIVE":
                continue
            if draft.object_type == "SECTION_REVISION":
                latest = latest_by_section.get(draft.object_id)
                if latest is None or latest.section_draft_id != draft.base_artifact_id:
                    self._drafts.mark_stale(
                        task_id,
                        author_id,
                        draft.draft_key,
                        reason="分节正式基线已变化，请基于最新版本重新修订",
                    )
            elif (
                draft.object_type in {
                    "RESEARCH_PROTOCOL_FORM", "ARGUMENT_MAP_FORM"
                }
                and state.current_ring_no != 5
            ):
                self._drafts.mark_stale(
                    task_id,
                    author_id,
                    draft.draft_key,
                    reason="论文已离开环5研究设计阶段，请回到允许环节后复核",
                )

    def get_workspace_state(
        self,
        workspace_key: str,
        *,
        tenant_id: str = "",
        author_id: str = "",
    ) -> Result[Dict[str, Any]]:
        raw = self._store.get_workspace(workspace_key)
        try:
            state = validate_workspace_state(raw or {})
        except ValueError:
            state = WorkspaceState()
        resume = None
        if state.last_task_id:
            rec = self._store.get(state.last_task_id)
            if rec is None or (tenant_id and rec.tenant_id != tenant_id):
                # 自愈幽灵指针属于服务端状态修改，revision 必须高于当前值，
                # 否则客户端仍在途的旧 POST 会把指针写回已不存在的任务。
                healed = WorkspaceState(
                    active_tab="refs",
                    revision=read_revision(raw) + 1,
                )
                self._store.put_workspace(
                    workspace_key,
                    healed.model_dump(exclude={"updated_at"}),
                )
                state = healed
            else:
                resume = self.get_resume_summary(
                    state.last_task_id, author_id=author_id
                ).data
        return Result.ok(data={
            "workspace": state.model_dump(),
            "resume": resume,
        }, msg="工作区恢复状态")

    # ------------------------------------------------------------------
    # 论文级项目记忆（版本化 + 作者审批）
    # ------------------------------------------------------------------

