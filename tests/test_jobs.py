"""持久化 JobRun、Worker 恢复、取消和 LLM 预算测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from common.llm import LLMClient, LLMSettings
from executor.base import ExecResult
from jobs import (
    JobBudgetExceededError,
    JobRegistry,
    JobRegistryError,
    JobRuntime,
    JobStatus,
    JobWorker,
    Pricing,
)
from jobs.runtime import job_runtime_context


def test_job_creation_is_idempotent_and_task_isolated():
    registry = JobRegistry()
    first = registry.create(
        task_id="task-a",
        session_id="session-a",
        operation="ring.execute",
        payload={"ring_no": 1},
        idempotency_key="ring-1-v1",
    )
    second = registry.create(
        task_id="task-a",
        session_id="session-a",
        operation="ring.execute",
        payload={"ring_no": 1},
        idempotency_key="ring-1-v1",
    )
    assert first.job_id == second.job_id
    assert first.status == JobStatus.PENDING
    with pytest.raises(JobRegistryError, match="当前任务"):
        registry.get("task-b", first.job_id)


def test_expired_lease_is_recovered_and_reclaimed():
    registry = JobRegistry()
    created = registry.create(
        task_id="task", session_id="session", operation="ring.execute",
        max_attempts=3,
    )
    first = registry.claim_next("worker-1", lease_seconds=10)
    assert first is not None and first.attempt == 1
    registry._db.execute(  # noqa: SLF001 - 精确模拟 Worker 崩溃后的过期租约
        "UPDATE t_job_run SET lease_expires_at='2000-01-01T00:00:00Z' WHERE job_id=?",
        (created.job_id,),
    )
    registry._db.commit()  # noqa: SLF001

    recovered = registry.claim_next("worker-2", lease_seconds=10)
    assert recovered is not None
    assert recovered.job_id == created.job_id
    assert recovered.attempt == 2
    assert recovered.lease_owner == "worker-2"


def test_cancel_and_manual_retry_state_machine():
    registry = JobRegistry()
    pending = registry.create(
        task_id="task", session_id="session", operation="ring.execute"
    )
    cancelled = registry.request_cancel("task", pending.job_id)
    assert cancelled.status == JobStatus.CANCELLED
    retried = registry.retry("task", pending.job_id)
    assert retried.status == JobStatus.PENDING
    assert retried.attempt == 0

    running = registry.claim_next("worker")
    assert running is not None
    requested = registry.request_cancel("task", running.job_id)
    assert requested.status == JobStatus.CANCEL_REQUESTED
    finished = registry.fail(
        running.job_id, "worker", "cancelled", retryable=False
    )
    assert finished.status == JobStatus.CANCELLED


def test_retryable_failure_respects_attempt_limit():
    registry = JobRegistry()
    job = registry.create(
        task_id="task", session_id="session", operation="unstable", max_attempts=2
    )
    first = registry.claim_next("worker-1")
    assert first is not None
    pending = registry.fail(
        job.job_id, "worker-1", "temporary", retryable=True, retry_delay_seconds=0
    )
    assert pending.status == JobStatus.PENDING
    second = registry.claim_next("worker-2")
    assert second is not None and second.attempt == 2
    failed = registry.fail(
        job.job_id, "worker-2", "still broken", retryable=True, retry_delay_seconds=0
    )
    assert failed.status == JobStatus.FAILED


def test_token_and_cost_budget_are_checked_before_calls_and_recorded():
    registry = JobRegistry()
    job = registry.create(
        task_id="task", session_id="session", operation="ring.execute",
        token_budget=150, cost_budget=0.001,
    )
    claimed = registry.claim_next("worker")
    assert claimed is not None
    runtime = JobRuntime(
        registry=registry,
        job_id=job.job_id,
        worker_id="worker",
        pricing=Pricing(input_per_million=1.0, output_per_million=2.0),
    )
    runtime.before_llm(estimated_input_tokens=40, max_output_tokens=50)
    runtime.record_llm_usage(input_tokens=40, output_tokens=20)
    current = registry.get_by_id(job.job_id)
    assert current.input_tokens == 40
    assert current.output_tokens == 20
    assert current.cost_used == pytest.approx(0.00008)
    with pytest.raises(JobBudgetExceededError, match="Token 预算不足"):
        runtime.before_llm(estimated_input_tokens=60, max_output_tokens=40)


def test_worker_marks_success_and_cooperatively_cancels():
    registry = JobRegistry()
    success = registry.create(
        task_id="task", session_id="session", operation="success"
    )
    worker = JobWorker(registry, {"success": lambda job: {"value": 42}})
    completed = worker.run_once()
    assert completed is not None
    assert completed.job_id == success.job_id
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.result == {"value": 42}

    cancelled = registry.create(
        task_id="task", session_id="session", operation="cancel"
    )

    def cancel_during_run(job):
        registry.request_cancel(job.task_id, job.job_id)
        return {"should_not_commit": True}

    cancelling_worker = JobWorker(registry, {"cancel": cancel_during_run})
    result = cancelling_worker.run_once()
    assert result is not None
    assert result.job_id == cancelled.job_id
    assert result.status == JobStatus.CANCELLED
    assert result.result == {}


def test_llm_client_records_provider_usage_in_current_job():
    class Output(BaseModel):
        answer: str

    registry = JobRegistry()
    job = registry.create(
        task_id="task", session_id="session", operation="ring.execute",
        token_budget=10_000, cost_budget=1.0,
    )
    registry.claim_next("worker")
    runtime = JobRuntime(
        registry=registry,
        job_id=job.job_id,
        worker_id="worker",
        pricing=Pricing(input_per_million=1.0, output_per_million=2.0),
    )
    client = LLMClient(
        LLMSettings(enabled=True, api_key="test-key", retry_max=0)
    )
    client._client = SimpleNamespace(  # noqa: SLF001 - provider test double
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content='{"answer":"ok"}'))
                    ],
                    usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
                )
            )
        )
    )
    with job_runtime_context(runtime):
        output = client.generate_json(
            system="Return JSON", prompt="JSON answer", model_cls=Output
        )
    assert output.answer == "ok"
    usage = registry.get_by_id(job.job_id)
    assert usage.input_tokens == 12
    assert usage.output_tokens == 8
    assert usage.cost_used == pytest.approx(0.000028)

    limited = registry.create(
        task_id="limited", session_id="session", operation="ring.execute",
        token_budget=100,
    )
    registry.claim_next("worker-limited")
    limited_runtime = JobRuntime(
        registry=registry,
        job_id=limited.job_id,
        worker_id="worker-limited",
        pricing=Pricing(),
    )
    with job_runtime_context(limited_runtime), pytest.raises(
        JobBudgetExceededError, match="Token 预算不足"
    ):
        client.generate_json(system="Return JSON", prompt="JSON answer", model_cls=Output)


class _Ring1Executor:
    def execute(self, ctx) -> ExecResult:
        return ExecResult(
            output=json.dumps(
                {
                    "candidates": [{"title": "后台作业论文"}],
                    "recommendation": "推荐",
                },
                ensure_ascii=False,
            ),
            accept=True,
            evidence={"source": "test-double"},
        )


def test_console_job_api_executes_ring_idempotently(monkeypatch):
    from application.main import build_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Ring1Executor(),
    )
    orchestration = MainOrchestration(job_registry=JobRegistry())
    task_id = orchestration.create_task(
        "后台任务", Degree.MASTER, "计算机科学", session_id="jobs-api"
    ).data["task_id"]
    app = build_app(orchestration=orchestration)
    client = TestClient(app)
    url = f"/api/v1/console/tasks/{task_id}/jobs?session_id=jobs-api"
    request = {
        "operation": "ring.execute",
        "payload": {"ring_no": 1},
        "idempotency_key": "execute-ring-1",
        "token_budget": 8_000,
    }
    first = client.post(url, json=request).json()
    second = client.post(url, json=request).json()
    assert first["data"]["job_id"] == second["data"]["job_id"]

    completed = app.state.job_worker.run_once()
    assert completed is not None and completed.status == JobStatus.SUCCEEDED
    detail = client.get(
        f"/api/v1/console/tasks/{task_id}/jobs/{completed.job_id}?session_id=jobs-api"
    ).json()
    assert detail["data"]["status"] == "SUCCEEDED"
    assert detail["data"]["result"]["code"] == 0
    assert orchestration.progress(task_id).data["phase_state"] == "WAITING_APPROVAL"
    orchestration.confirm_ring(task_id, 1)
    artifact = orchestration.list_artifacts(task_id).data[0]
    assert artifact["context_manifest"]["job_id"] == completed.job_id
    assert artifact["context_manifest"]["token_budget"] == 8_000
