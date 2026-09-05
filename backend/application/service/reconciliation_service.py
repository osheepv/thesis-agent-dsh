"""Startup and runtime consistency reconciliation."""

from __future__ import annotations

from typing import Any, Dict

from artifacts import ArtifactKind
from common.aicoding.dto.result import Result
from common.aicoding.enums.phase_state import PhaseState
from common.workflow_contracts import get_stage_contract
from writing import SectionDraftStatus


class ReconciliationServiceMixin:
    """Cross-store audit with narrowly scoped automatic recovery."""

    @staticmethod
    def _reconciliation_issue(code: str, domain: str, message: str) -> Dict[str, str]:
        return {"code": code, "domain": domain, "message": message}

    def reconcile_startup(self) -> Result[Dict[str, Any]]:
        global_issues: list[dict[str, str]] = []
        try:
            recovered_jobs = self._jobs.recover_expired()
        except Exception:  # noqa: BLE001
            recovered_jobs = 0
            global_issues.append({
                "code": "JOB_STORE_UNREADABLE",
                "domain": "job",
                "task_id": "",
            })
        try:
            records = self._store.all()
            task_store_readable = True
        except Exception:  # noqa: BLE001
            records = []
            task_store_readable = False
            global_issues.append({
                "code": "TASK_STORE_UNREADABLE",
                "domain": "task",
                "task_id": "",
            })
        task_ids = {record.task_id for record in records}
        reports = [
            self.reconcile_task_state(record.task_id, recover_jobs=False).data
            for record in records
        ]
        domains = (
            ("FSM", self._fsm.list_task_ids),
            ("ARTIFACT", self._artifacts.list_task_ids),
            ("SECTION", self._sections.list_task_ids),
            ("JOB", self._jobs.list_task_ids),
        )
        for domain, task_id_loader in domains:
            try:
                domain_task_ids = set(task_id_loader())
            except Exception:  # noqa: BLE001
                global_issues.append({
                    "code": f"{domain}_STORE_UNREADABLE",
                    "domain": domain.lower(),
                    "task_id": "",
                })
                continue
            if not task_store_readable:
                continue
            for orphan_task_id in sorted(domain_task_ids - task_ids):
                global_issues.append(
                    {
                        "code": f"ORPHAN_{domain}_TASK",
                        "domain": domain.lower(),
                        "task_id": orphan_task_id,
                    }
                )
        self._global_reconciliation_issues = global_issues
        return Result.ok(
            data={
                "status": "NEEDS_REPAIR" if global_issues or any(
                    report["status"] != "CONSISTENT" for report in reports
                ) else "CONSISTENT",
                "task_count": len(records),
                "inconsistent_task_count": sum(
                    report["status"] != "CONSISTENT" for report in reports
                ),
                "recovered_job_count": recovered_jobs,
                "global_issues": global_issues,
                "tasks": reports,
            },
            msg="启动对账完成",
        )

    def reconcile_task_state(
        self, task_id: str, *, recover_jobs: bool = True
    ) -> Result[Dict[str, Any]]:
        issues: list[dict[str, str]] = []
        artifact_projection_issues: list[str] = []
        try:
            recovered_jobs = self._jobs.recover_expired() if recover_jobs else 0
        except Exception:  # noqa: BLE001
            recovered_jobs = 0
            issues.append(self._reconciliation_issue(
                "JOB_STORE_UNREADABLE", "job", "作业存储无法读取或恢复"
            ))
        record = self._store.get(task_id)
        if record is None:
            issues.append(self._reconciliation_issue(
                "TASK_RECORD_MISSING", "task", "应用任务记录不存在"
            ))
            return self._reconciliation_result(
                task_id, issues, artifact_projection_issues, recovered_jobs
            )

        try:
            state = self._fsm.get_task(task_id)
        except Exception:  # noqa: BLE001
            issues.append(self._reconciliation_issue(
                "FSM_STATE_MISSING", "fsm", "FSM 状态不存在或无法读取"
            ))
            return self._reconciliation_result(
                task_id, issues, artifact_projection_issues, recovered_jobs
            )

        mismatched_fields = [
            field_name
            for field_name in ("title", "subject_field")
            if str(getattr(record, field_name, "")) != str(getattr(state, field_name, ""))
        ]
        if str(record.degree) != str(getattr(state.degree, "value", state.degree)):
            mismatched_fields.append("degree")
        if mismatched_fields:
            issues.append(self._reconciliation_issue(
                "TASK_FSM_METADATA_MISMATCH",
                "fsm",
                "任务与 FSM 元数据不一致: " + ",".join(mismatched_fields),
            ))

        artifact_projection_issues = list(self._project_pending_artifacts(task_id))
        if artifact_projection_issues:
            issues.append(self._reconciliation_issue(
                "ARTIFACT_PROJECTION_PENDING", "artifact", "产物 Outbox 尚未完成投影"
            ))

        completed_rings = list(range(1, state.current_ring_no))
        if state.current_ring_no == 10 and state.phase_state == PhaseState.PASSED:
            completed_rings.append(10)
        for ring_no in completed_rings:
            if getattr(record, f"ring{ring_no}", None) is None:
                issues.append(self._reconciliation_issue(
                    "COMPLETED_RING_PAYLOAD_MISSING",
                    "task",
                    f"已完成环{ring_no}缺少任务产物",
                ))
            runtime_kind = ArtifactKind(get_stage_contract(ring_no).runtime_artifact_kind)
            try:
                active = self._artifacts.get_active(
                    task_id=task_id, stage_no=ring_no, kind=runtime_kind
                )
            except Exception:  # noqa: BLE001
                issues.append(self._reconciliation_issue(
                    "ARTIFACT_STORE_UNREADABLE", "artifact", "产物存储无法读取"
                ))
                break
            if active is None:
                issues.append(self._reconciliation_issue(
                    "COMPLETED_RING_ARTIFACT_MISSING",
                    "artifact",
                    f"已完成环{ring_no}缺少有效批准产物",
                ))

        if state.phase_state == PhaseState.WAITING_APPROVAL:
            ring_no = state.current_ring_no
            if getattr(record, f"ring{ring_no}", None) is None:
                issues.append(self._reconciliation_issue(
                    "CURRENT_RING_PAYLOAD_MISSING",
                    "task",
                    f"待审批环{ring_no}缺少任务产物",
                ))
            if str(ring_no) not in state.artifacts:
                issues.append(self._reconciliation_issue(
                    "CURRENT_FSM_ARTIFACT_MISSING",
                    "fsm",
                    f"待审批环{ring_no}缺少 FSM 产物指针",
                ))

        try:
            section_drafts = self._sections.list_task(task_id)
        except Exception:  # noqa: BLE001
            section_drafts = []
            issues.append(self._reconciliation_issue(
                "SECTION_STORE_UNREADABLE", "section", "分节存储无法读取"
            ))
        if section_drafts:
            self._refresh_section_staleness(task_id)
            section_drafts = self._sections.list_task(task_id)
            referenced_ids = set((record.ring6 or {}).get("section_draft_ids", []) or [])
            known_ids = {draft.section_draft_id for draft in section_drafts}
            if referenced_ids - known_ids:
                issues.append(self._reconciliation_issue(
                    "SECTION_DRAFT_REFERENCE_MISSING",
                    "section",
                    "环6引用的分节版本不存在",
                ))
            if state.current_ring_no > 6 and any(
                draft.section_draft_id in referenced_ids
                and draft.status != SectionDraftStatus.APPROVED
                for draft in section_drafts
            ):
                issues.append(self._reconciliation_issue(
                    "APPROVED_SECTION_DRAFT_STALE",
                    "section",
                    "已汇编分节在后续环节前变为失效状态",
                ))

        if record.session_id and self._knowledge_store is not None:
            try:
                knowledge_store = self._knowledge_store
                if hasattr(knowledge_store, "audit_session"):
                    audit = knowledge_store.audit_session(record.session_id)
                    for issue_code in audit.get("issues", []) or []:
                        issues.append(self._reconciliation_issue(
                            str(issue_code), "knowledge", "知识库索引或文件血缘不一致"
                        ))
                else:
                    knowledge_store.list_documents(record.session_id)
            except Exception:  # noqa: BLE001
                issues.append(self._reconciliation_issue(
                    "KNOWLEDGE_STORE_UNREADABLE", "knowledge", "知识库无法读取"
                ))

        return self._reconciliation_result(
            task_id, issues, artifact_projection_issues, recovered_jobs
        )

    def _reconciliation_result(
        self,
        task_id: str,
        issues: list[dict[str, str]],
        artifact_projection_issues: list[str],
        recovered_jobs: int,
    ) -> Result[Dict[str, Any]]:
        unique_issues = list({issue["code"]: issue for issue in issues}.values())
        if not hasattr(self, "_reconciliation_issues"):
            self._reconciliation_issues = {}
        self._reconciliation_issues[task_id] = unique_issues
        return Result.ok(
            data={
                "task_id": task_id,
                "status": "NEEDS_REPAIR" if unique_issues else "CONSISTENT",
                "blocking_count": len(unique_issues),
                "issues": unique_issues,
                "artifact_projection_issues": artifact_projection_issues,
                "recovered_job_count": recovered_jobs,
            },
            msg="任务状态对账完成",
        )
