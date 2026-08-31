# -*- coding: utf-8 -*-
"""Job service mixin."""
from __future__ import annotations

from typing import Any, Dict, List

from common.aicoding.dto.result import Result
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from common.aicoding.enums.phase_state import PhaseState
from jobs import JobRegistryError, PermanentJobError, Pricing


class JobServiceMixin:
    """Job enqueue, list, cancel, retry and handler registration."""

    def enqueue_job(self, task_id: str, value: Dict[str, Any]) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        operation = str(value.get("operation", "")).strip()
        if operation not in self._JOB_OPERATIONS:
            raise JobRegistryError(f"不支持的后台作业 operation: {operation}")
        cost_budget = float(value.get("cost_budget", 0) or 0)
        pricing = Pricing.from_env()
        if cost_budget > 0 and (
            pricing.input_per_million <= 0 or pricing.output_per_million <= 0
        ):
            raise JobRegistryError(
                "设置费用预算前必须配置 THESIS_LLM_INPUT_COST_PER_MILLION 和 "
                "THESIS_LLM_OUTPUT_COST_PER_MILLION"
            )
        job = self._jobs.create(
            task_id=task_id,
            session_id=rec.session_id,
            operation=operation,
            payload=dict(value.get("payload", {}) or {}),
            idempotency_key=str(value.get("idempotency_key", "")),
            max_attempts=int(value.get("max_attempts", 3) or 3),
            priority=int(value.get("priority", 0) or 0),
            token_budget=int(value.get("token_budget", 0) or 0),
            cost_budget=cost_budget,
        )
        return Result.ok(data=job.to_dict(), msg="后台作业已入队")

    def list_jobs(self, task_id: str, limit: int = 100) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[job.to_dict() for job in self._jobs.list_task(task_id, limit=limit)],
            msg="后台作业列表",
        )

    def get_job(self, task_id: str, job_id: str) -> Result[Dict[str, Any]]:
        self._require(task_id)
        return Result.ok(data=self._jobs.get(task_id, job_id).to_dict(), msg="后台作业详情")

    def cancel_job(self, task_id: str, job_id: str) -> Result[Dict[str, Any]]:
        self._require(task_id)
        job = self._jobs.request_cancel(task_id, job_id)
        return Result.ok(data=job.to_dict(), msg="取消请求已记录")

    def retry_job(self, task_id: str, job_id: str) -> Result[Dict[str, Any]]:
        self._require(task_id)
        job = self._jobs.retry(task_id, job_id)
        return Result.ok(data=job.to_dict(), msg="后台作业已重新入队")

    def job_handlers(self) -> Dict[str, Any]:
        return {
            "ring.execute": self._job_execute_ring,
            "section.generate": self._job_generate_section,
            "sections.generate_all": self._job_generate_all_sections,
            "docx.generate": self._job_generate_docx,
        }

    def _job_execute_ring(self, job) -> Dict[str, Any]:
        ring_no = int(job.payload.get("ring_no", 0) or 0)
        runners = {
            1: self.run_ring1,
            2: self.run_ring2,
            3: self.run_ring3,
            4: self.run_ring4,
            5: self.run_ring5,
            6: self.run_ring6,
            7: self.run_ring7,
            8: self.run_ring8,
            9: self.run_ring9,
            10: self.run_ring10,
        }
        if ring_no not in runners:
            raise PermanentJobError("ring_no 必须在 1..10")
        rec = self._require(job.task_id)
        state = self._fsm.get_task(job.task_id)
        existing = getattr(rec, f"ring{ring_no}", None)
        if existing is not None and (
            state.current_ring_no > ring_no
            or (
                state.current_ring_no == ring_no
                and state.phase_state == PhaseState.WAITING_APPROVAL
            )
            or state.phase_state == PhaseState.PASSED
        ):
            return {
                "code": 0,
                "msg": "作业重放时发现环产物已落库，已幂等恢复",
                "data": existing,
                "recovered": True,
            }
        result = runners[ring_no](job.task_id)
        if not result.is_ok:
            raise PermanentJobError(result.msg)
        rec = self._require(job.task_id)
        payload = getattr(rec, f"ring{ring_no}", None)
        if isinstance(payload, dict):
            payload["_job_id"] = job.job_id
            self._store.put(rec)
        return result.model_dump()

    def _job_generate_section(self, job) -> Dict[str, Any]:
        for draft in self._sections.list_task(job.task_id):
            if draft.context_manifest.get("job_id") == job.job_id:
                return {
                    "code": 0,
                    "msg": "作业重放时发现分节版本已落库，已幂等恢复",
                    "data": draft.to_dict(),
                    "recovered": True,
                }
        result = self.generate_section_draft(job.task_id, dict(job.payload))
        if not result.is_ok:
            raise PermanentJobError(result.msg)
        return result.model_dump()

    def _job_generate_all_sections(self, job) -> Dict[str, Any]:
        result = self.generate_all_section_drafts(job.task_id)
        if not result.is_ok:
            raise PermanentJobError(result.msg)
        return result.model_dump()

    def _job_generate_docx(self, job) -> Dict[str, Any]:
        rec = self._require(job.task_id)
        if rec.docx:
            return {
                "code": 0,
                "msg": "作业重放时发现 DOCX 已生成，已幂等恢复",
                "data": rec.docx,
                "recovered": True,
            }
        result = self.generate_docx(
            job.task_id,
            template_id=str(job.payload.get("template_id", "")) or None,
        )
        if not result.is_ok:
            raise PermanentJobError(result.msg)
        return result.model_dump()


