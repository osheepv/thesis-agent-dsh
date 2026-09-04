# -*- coding: utf-8 -*-
"""研究域服务（从 uc_main_orchestration.py 拆出的 mixin）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from common.aicoding.dto.result import Result
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from common.workflow_contracts import get_stage_contract

from artifacts import ArtifactKind, ArtifactStatus, ContextManifest
from evidence import ClaimType
from research import (
    ArgumentClaimSpec,
    ArgumentMap,
    ArgumentRole,
    EpistemicIntent,
    ExperimentStatus,
    ResearchExecutionRegistry,
    ResearchMethod,
    ResearchProtocol,
    ResearchRegistryError,
)

from application.service.task_store import TaskRecord


class ResearchServiceMixin:
    """论证图、研究协议、实验运行、结果账本与审计。"""

    def create_argument_map(
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
            object_type="ARGUMENT_MAP_FORM",
            object_id="new",
            tenant_id=tenant_id,
            author_id=author_id,
        )
        self._assert_autosave_content_matches(autosave, payload)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 5:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="论证图只能在环5设计和审批",
            )
        claims: list[ArgumentClaimSpec] = []
        for raw in payload.get("claims", ()) or ():
            if not isinstance(raw, dict):
                raise ResearchRegistryError("论证图 claims 条目必须是对象")
            try:
                claim_type = ClaimType(str(raw.get("claim_type", "FACTUAL")))
                role = ArgumentRole(str(raw.get("role", "CLAIM")))
                epistemic_intent = EpistemicIntent(
                    str(raw.get("epistemic_intent", EpistemicIntent.ASSERTION.value))
                )
            except ValueError as exc:
                raise ResearchRegistryError(f"非法论断类型或角色: {raw}") from exc
            claims.append(
                ArgumentClaimSpec(
                    claim_key=str(raw.get("claim_key", "")),
                    text=str(raw.get("text", "")),
                    section_id=str(raw.get("section_id", "")),
                    claim_type=claim_type,
                    role=role,
                    epistemic_intent=epistemic_intent,
                    parent_keys=tuple(raw.get("parent_keys", ()) or ()),
                    evidence_requirements=tuple(
                        raw.get("evidence_requirements", ()) or ()
                    ),
                )
            )
        argument_map = ArgumentMap(
            title=str(payload.get("title", "")),
            research_questions=tuple(payload.get("research_questions", ()) or ()),
            claims=tuple(claims),
        )
        ring4 = self._artifacts.get_active(
            task_id=task_id,
            stage_no=4,
            kind=ArtifactKind(get_stage_contract(4).runtime_artifact_kind),
        )
        if ring4 is None:
            raise ResearchRegistryError("创建论证图前缺少环4有效批准产物")
        protocol = self._active_research_protocol(task_id)
        protocol_versions = [
            artifact
            for artifact in self._artifacts.list_task(task_id)
            if artifact.kind == ArtifactKind.RESEARCH_PROTOCOL
        ]
        if protocol_versions and protocol is None:
            raise ResearchRegistryError("研究协议尚未批准，不能据此创建论证图")
        dependencies = (ring4.artifact_id,) + (
            (protocol.artifact_id,) if protocol is not None else ()
        )
        artifact = self._artifacts.create_version(
            task_id=task_id,
            stage_no=5,
            kind=ArtifactKind.ARGUMENT_MAP,
            payload=argument_map.to_dict(),
            dependency_ids=dependencies,
            context_manifest=ContextManifest(
                prompt_id="argument_map",
                prompt_version="v1",
                input_artifact_ids=dependencies,
            ),
        )
        artifact = self._artifacts.submit_auto_gate(
            artifact.artifact_id,
            passed=True,
            report={"graph_validation": "passed", "claim_count": len(claims)},
        )
        data = self._artifact_dict(artifact)
        submitted_draft = self._complete_autosave_submission(
            autosave, artifact.artifact_id
        )
        if submitted_draft is not None:
            data["autosave_draft"] = submitted_draft.metadata()
        return Result.ok(data=data, msg="论证图已生成，等待作者审批")

    def review_argument_map(
        self, task_id: str, artifact_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        artifact = self._artifacts.get(artifact_id)
        if artifact.task_id != task_id or artifact.kind != ArtifactKind.ARGUMENT_MAP:
            raise ResearchRegistryError("当前任务中不存在该论证图")
        if artifact.status == ArtifactStatus.WAITING_APPROVAL:
            artifact = self._artifacts.decide(
                artifact_id, approved=approved, actor=actor, reason=reason
            )
        elif artifact.status != ArtifactStatus.APPROVED or not approved:
            raise ResearchRegistryError("该论证图当前状态不能重复审批")
        if artifact.status == ArtifactStatus.APPROVED:
            self._sync_argument_map_claims(task_id, artifact)
        return Result.ok(data=self._artifact_dict(artifact), msg="论证图审批已记录")

    def list_argument_maps(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        active = self._active_argument_map(task_id)
        if active is not None:
            self._sync_argument_map_claims(task_id, active)
        return Result.ok(
            data=[
                self._artifact_dict(artifact)
                for artifact in self._artifacts.list_task(task_id)
                if artifact.kind == ArtifactKind.ARGUMENT_MAP
            ],
            msg="论证图列表",
        )

    def _sync_argument_map_claims(self, task_id: str, artifact) -> None:
        for raw in artifact.payload.get("claims", []) or []:
            self._evidence.add_claim(
                task_id=task_id,
                text=str(raw.get("text", "")),
                artifact_id=artifact.artifact_id,
                section_id=str(raw.get("section_id", "")),
                claim_type=ClaimType(str(raw.get("claim_type", "FACTUAL"))),
                source_key=f"{artifact.artifact_id}:{raw.get('claim_key', '')}",
            )

    def create_research_protocol(
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
            object_type="RESEARCH_PROTOCOL_FORM",
            object_id="new",
            tenant_id=tenant_id,
            author_id=author_id,
        )
        self._assert_autosave_content_matches(autosave, payload)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 5:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="研究协议只能在环5设计和审批",
            )
        method_value = str(payload.get("method", ""))
        try:
            method = ResearchMethod(method_value)
        except ValueError as exc:
            raise ResearchRegistryError(f"非法研究方法: {method_value}") from exc
        protocol = ResearchProtocol(
            title=str(payload.get("title", "")),
            method=method,
            research_questions=tuple(payload.get("research_questions", ()) or ()),
            procedure_steps=tuple(payload.get("procedure_steps", ()) or ()),
            analysis_plan=tuple(payload.get("analysis_plan", ()) or ()),
            required_outputs=tuple(payload.get("required_outputs", ()) or ()),
            hypotheses=tuple(payload.get("hypotheses", ()) or ()),
            variables=dict(payload.get("variables", {}) or {}),
            materials=tuple(payload.get("materials", ()) or ()),
            ethics_requirements=tuple(payload.get("ethics_requirements", ()) or ()),
            risks=tuple(payload.get("risks", ()) or ()),
        )
        ring4 = self._artifacts.get_active(
            task_id=task_id,
            stage_no=4,
            kind=ArtifactKind(get_stage_contract(4).runtime_artifact_kind),
        )
        if ring4 is None:
            raise ResearchRegistryError("创建研究协议前缺少环4有效批准产物")
        artifact = self._artifacts.create_version(
            task_id=task_id,
            stage_no=5,
            kind=ArtifactKind.RESEARCH_PROTOCOL,
            payload=protocol.to_dict(),
            dependency_ids=(ring4.artifact_id,),
            context_manifest=ContextManifest(
                prompt_id="research_protocol",
                prompt_version="v1",
                input_artifact_ids=(ring4.artifact_id,),
            ),
        )
        artifact = self._artifacts.submit_auto_gate(
            artifact.artifact_id,
            passed=True,
            report={"schema_validation": "passed", "requires_author_approval": True},
        )
        data = self._artifact_dict(artifact)
        submitted_draft = self._complete_autosave_submission(
            autosave, artifact.artifact_id
        )
        if submitted_draft is not None:
            data["autosave_draft"] = submitted_draft.metadata()
        return Result.ok(data=data, msg="研究协议已生成，等待作者审批")

    def review_research_protocol(
        self, task_id: str, artifact_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        artifact = self._artifacts.get(artifact_id)
        if artifact.task_id != task_id or artifact.kind != ArtifactKind.RESEARCH_PROTOCOL:
            raise ResearchRegistryError("当前任务中不存在该研究协议")
        decided = self._artifacts.decide(
            artifact_id, approved=approved, actor=actor, reason=reason
        )
        return Result.ok(data=self._artifact_dict(decided), msg="研究协议审批已记录")

    def list_research_protocols(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[
                self._artifact_dict(artifact)
                for artifact in self._artifacts.list_task(task_id)
                if artifact.kind == ArtifactKind.RESEARCH_PROTOCOL
            ],
            msg="研究协议列表",
        )

    def create_experiment_run(
        self, task_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        protocol = self._active_research_protocol(task_id)
        if protocol is None:
            raise ResearchRegistryError("须先批准研究协议，才能创建实验运行")
        run = self._research.create_run(
            task_id=task_id,
            protocol_artifact_id=protocol.artifact_id,
            notes=str(value.get("notes", "")),
        )
        return Result.ok(data=run.to_dict(), msg="实验运行已创建")

    def update_experiment_run(
        self, task_id: str, run_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        status_value = str(value.get("status", ""))
        try:
            status = ExperimentStatus(status_value)
        except ValueError as exc:
            raise ResearchRegistryError(f"非法实验状态: {status_value}") from exc
        submitted_file_ids = {
            str(file_id)
            for key in (
                "material_file_ids", "raw_data_file_ids", "code_file_ids", "log_file_ids"
            )
            for file_id in (value.get(key) or [])
            if str(file_id)
        }
        self._validate_knowledge_file_ids(rec, submitted_file_ids)
        run = self._research.update_run(
            task_id=task_id,
            run_id=run_id,
            status=status,
            material_file_ids=value.get("material_file_ids"),
            raw_data_file_ids=value.get("raw_data_file_ids"),
            code_file_ids=value.get("code_file_ids"),
            log_file_ids=value.get("log_file_ids"),
            notes=value.get("notes"),
            user_attested=value.get("user_attested"),
        )
        return Result.ok(data=run.to_dict(), msg="实验运行状态已更新")

    def list_experiment_runs(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[run.to_dict() for run in self._research.list_runs(task_id)],
            msg="实验运行列表",
        )

    def add_result_record(
        self, task_id: str, run_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        source_file_id = str(value.get("source_file_id", ""))
        self._validate_knowledge_file_ids(rec, {source_file_id} if source_file_id else set())
        result = self._research.add_result(
            task_id=task_id,
            run_id=run_id,
            metric=str(value.get("metric", "")),
            value=str(value.get("value", "")),
            source_file_id=source_file_id,
            computation=str(value.get("computation", "")),
            unit=str(value.get("unit", "")),
            table_or_figure_id=str(value.get("table_or_figure_id", "")),
        )
        return Result.ok(data=result.to_dict(), msg="结果记录已登记，等待作者核验")

    def review_result_record(
        self, task_id: str, result_id: str, *, verified_by_user: bool
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        result = self._research.review_result(
            task_id, result_id, verified_by_user=verified_by_user
        )
        return Result.ok(data=result.to_dict(), msg="结果核验状态已记录")

    def list_result_records(self, task_id: str, run_id: str = "") -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[
                result.to_dict()
                for result in self._research.list_results(task_id, run_id=run_id)
            ],
            msg="结果记录列表",
        )

    def audit_research(self, task_id: str) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        protocol = self._active_research_protocol(task_id)
        if protocol is None:
            return Result.ok(
                data={
                    "task_id": task_id,
                    "protocol_artifact_id": "",
                    "requires_execution": False,
                    "can_write_results": False,
                    "blocking_items": ["缺少已批准的研究协议"],
                },
                msg="研究实施审计完成",
            )
        data = self._research.audit(task_id, protocol.artifact_id)
        requires_execution = self._method_requires_execution(protocol.payload)
        blockers: list[str] = []
        if requires_execution and data["completed_run_count"] == 0:
            blockers.append("缺少用户确认完成的实验/研究运行")
        if requires_execution and data["verified_result_count"] == 0:
            blockers.append("缺少经用户核验、可追溯到原始文件的结果记录")
        referenced_file_ids = {
            str(file_id)
            for run in data.get("runs", [])
            for key in (
                "material_file_ids", "raw_data_file_ids", "code_file_ids", "log_file_ids"
            )
            for file_id in (run.get(key, []) or [])
        }
        referenced_file_ids.update(
            str(result.get("source_file_id", ""))
            for result in data.get("results", [])
            if str(result.get("source_file_id", ""))
        )
        missing_file_ids = sorted(
            referenced_file_ids - self._available_knowledge_file_ids(rec)
        )
        if missing_file_ids:
            blockers.append(f"实验/结果引用的知识库文件已缺失: {missing_file_ids}")
        data.update(
            {
                "method": str(protocol.payload.get("method", "")),
                "requires_execution": requires_execution,
                "can_write_results": not blockers,
                "blocking_items": blockers,
                "missing_file_ids": missing_file_ids,
            }
        )
        return Result.ok(data=data, msg="研究实施审计完成")

    def _available_knowledge_file_ids(self, rec: TaskRecord) -> set[str]:
        store = self._knowledge_store
        if store is None:
            from knowledge.store import get_kb_store

            store = get_kb_store()
        return {
            str(item.get("file_id", ""))
            for item in store.list_documents(rec.session_id)
            if str(item.get("file_id", ""))
        }

    def _validate_knowledge_file_ids(
        self, rec: TaskRecord, file_ids: set[str]
    ) -> None:
        if not file_ids:
            return
        missing = sorted(file_ids - self._available_knowledge_file_ids(rec))
        if missing:
            raise ResearchRegistryError(
                f"实验文件不属于当前任务知识库或已被删除: {missing}"
            )

    def create_result_ledger(self, task_id: str) -> Result[Dict[str, Any]]:
        self._require(task_id)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 6:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="结果账本只能在环6生成和审批",
            )
        audit = self.audit_research(task_id).data
        if not audit.get("can_write_results"):
            raise ResearchRegistryError("研究材料尚未满足结果写作门禁")
        protocol = self._active_research_protocol(task_id)
        if protocol is None:
            raise ResearchRegistryError("缺少已批准的研究协议")
        outline = self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
        )
        if outline is None:
            raise ResearchRegistryError("生成结果账本前缺少已批准大纲")
        payload = {
            **audit,
            "results": [
                result
                for result in audit.get("results", [])
                if bool(result.get("verified_by_user"))
            ],
        }
        artifact = self._artifacts.create_version(
            task_id=task_id,
            stage_no=6,
            kind=ArtifactKind.RESULT_LEDGER,
            payload=payload,
            dependency_ids=(protocol.artifact_id, outline.artifact_id),
            context_manifest=ContextManifest(
                prompt_id="result_ledger",
                prompt_version="v1",
                input_artifact_ids=(protocol.artifact_id, outline.artifact_id),
            ),
        )
        artifact = self._artifacts.submit_auto_gate(
            artifact.artifact_id,
            passed=True,
            report={"research_audit": "passed", "verified_results": len(payload["results"])},
        )
        return Result.ok(data=self._artifact_dict(artifact), msg="结果账本已生成，等待作者审批")

    def review_result_ledger(
        self, task_id: str, artifact_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        artifact = self._artifacts.get(artifact_id)
        if artifact.task_id != task_id or artifact.kind != ArtifactKind.RESULT_LEDGER:
            raise ResearchRegistryError("当前任务中不存在该结果账本")
        decided = self._artifacts.decide(
            artifact_id, approved=approved, actor=actor, reason=reason
        )
        return Result.ok(data=self._artifact_dict(decided), msg="结果账本审批已记录")

    def _active_research_protocol(self, task_id: str):
        return self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.RESEARCH_PROTOCOL
        )

    def _active_argument_map(self, task_id: str):
        return self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.ARGUMENT_MAP
        )

    def _active_project_memory(self, task_id: str):
        return self._artifacts.get_active(
            task_id=task_id, stage_no=1, kind=ArtifactKind.PROJECT_MEMORY
        )
