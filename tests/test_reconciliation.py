"""启动对账、跨仓储阻断与 Worker 租约恢复。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration, _TaskStore
from artifacts import ArtifactKind, ArtifactRegistry
from common.aicoding.enums import Degree
from common.aicoding.exception.biz_exception import BizException
from executor.base import ExecResult
from knowledge.store import KnowledgeStore
from jobs import JobRegistry
from writing import SectionDraftRegistry


class _Ring1Executor:
    def execute(self, _ctx) -> ExecResult:
        return ExecResult(
            output=json.dumps(
                {
                    "candidates": [{"title": "可恢复论文任务"}],
                    "recommendation": "推荐",
                },
                ensure_ascii=False,
            ),
            accept=True,
            evidence={"source": "test-double"},
        )


def _orchestration(monkeypatch, **kwargs) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda _ring_no: _Ring1Executor(),
    )
    return MainOrchestration(**kwargs)


def _waiting_ring1(orchestration: MainOrchestration, session_id: str) -> str:
    task_id = orchestration.create_task(
        "启动对账", Degree.MASTER, "计算机科学", session_id=session_id
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 0})
    return task_id


def test_clean_task_survives_startup_reconciliation(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _waiting_ring1(orchestration, "reconcile-clean")
    orchestration.confirm_ring(task_id, 1)

    report = orchestration.reconcile_startup().data

    assert report["status"] == "CONSISTENT"
    assert report["task_count"] == 1
    assert report["inconsistent_task_count"] == 0
    assert report["global_issues"] == []
    assert report["tasks"][0]["task_id"] == task_id


def test_restart_reopens_persisted_stores_with_consistent_state(monkeypatch, tmp_path):
    from fsm.orchestrator import FsmOrchestrator
    from fsm.repository import SqlAlchemyFsmRepository
    from fsm.state.orm import FSMBase
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'fsm.db'}")
    FSMBase.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    common = {
        "store": _TaskStore(db_path=str(tmp_path / "tasks.db")),
        "artifact_registry": ArtifactRegistry(tmp_path / "artifacts.db"),
        "section_registry": SectionDraftRegistry(tmp_path / "sections.db"),
        "job_registry": JobRegistry(tmp_path / "jobs.db"),
    }
    first = _orchestration(
        monkeypatch,
        fsm=FsmOrchestrator(SqlAlchemyFsmRepository(sessions)),
        **common,
    )
    task_id = _waiting_ring1(first, "reconcile-restart")
    first.confirm_ring(task_id, 1)

    second = _orchestration(
        monkeypatch,
        fsm=FsmOrchestrator(SqlAlchemyFsmRepository(sessions)),
        store=_TaskStore(db_path=str(tmp_path / "tasks.db")),
        artifact_registry=ArtifactRegistry(tmp_path / "artifacts.db"),
        section_registry=SectionDraftRegistry(tmp_path / "sections.db"),
        job_registry=JobRegistry(tmp_path / "jobs.db"),
    )
    report = second.reconcile_startup().data

    assert report["status"] == "CONSISTENT"
    assert report["tasks"][0]["task_id"] == task_id
    assert second.progress(task_id).data["current_ring_no"] == 2


def test_missing_waiting_payload_blocks_confirmation_and_resume(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _waiting_ring1(orchestration, "reconcile-block")
    record = orchestration._store.get(task_id)  # noqa: SLF001
    record.ring1 = None
    orchestration._store.put(record)  # noqa: SLF001

    report = orchestration.reconcile_task_state(task_id).data

    assert report["status"] == "NEEDS_REPAIR"
    assert [issue["code"] for issue in report["issues"]] == [
        "CURRENT_RING_PAYLOAD_MISSING"
    ]
    with pytest.raises(BizException, match="对账未通过"):
        orchestration.confirm_ring(task_id, 1)
    resume = orchestration.get_resume_summary(task_id).data
    assert resume["consistency_status"] == "NEEDS_REPAIR"
    assert resume["stop_reason_code"] == "STARTUP_RECONCILIATION_REQUIRED"
    assert resume["blocking_count"] == 1
    assert resume["consistency_issues"] == ["CURRENT_RING_PAYLOAD_MISSING"]
    assert resume["next_safe_action"]["type"] == "REPAIR_REQUIRED"
    client = TestClient(build_app(orchestration=orchestration))
    response = client.get(
        f"/api/v1/console/tasks/{task_id}/reconciliation",
        params={"session_id": "reconcile-block"},
    ).json()
    assert response["data"]["status"] == "NEEDS_REPAIR"
    assert response["data"]["issues"][0]["code"] == "CURRENT_RING_PAYLOAD_MISSING"


def test_startup_recovers_expired_worker_lease(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "Worker 恢复", Degree.MASTER, "计算机科学", session_id="worker-recover"
    ).data["task_id"]
    job = orchestration._jobs.create(  # noqa: SLF001
        task_id=task_id,
        session_id="worker-recover",
        operation="ring.execute",
        payload={"ring_no": 1},
        max_attempts=2,
    )
    orchestration._jobs.claim_next("worker-before-crash", lease_seconds=10)  # noqa: SLF001
    orchestration._jobs._db.execute(  # noqa: SLF001
        "UPDATE t_job_run SET lease_expires_at='2000-01-01T00:00:00Z' WHERE job_id=?",
        (job.job_id,),
    )
    orchestration._jobs._db.commit()  # noqa: SLF001

    report = orchestration.reconcile_startup().data
    recovered = orchestration._jobs.get(task_id, job.job_id)  # noqa: SLF001

    assert report["recovered_job_count"] == 1
    assert recovered.status.value == "PENDING"
    assert recovered.lease_owner == ""
    assert recovered.error == "Worker 租约过期，已恢复"


def test_startup_reports_orphan_domain_records(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    orphan_task_id = "TASK-ORPHAN"
    orchestration._fsm.create_task(  # noqa: SLF001
        "孤立 FSM", Degree.MASTER, "计算机科学", task_id=orphan_task_id
    )
    orchestration._artifacts.create_version(  # noqa: SLF001
        task_id=orphan_task_id,
        stage_no=1,
        kind=ArtifactKind.TOPIC_PROPOSAL,
        payload={"title": "orphan"},
    )
    orchestration._sections.create_version(  # noqa: SLF001
        task_id=orphan_task_id,
        section_id="1.1",
        title="孤立分节",
        content="孤立正文",
    )
    orchestration._jobs.create(  # noqa: SLF001
        task_id=orphan_task_id,
        session_id="orphan",
        operation="ring.execute",
    )

    report = orchestration.reconcile_startup().data
    issue_codes = {issue["code"] for issue in report["global_issues"]}

    assert report["status"] == "NEEDS_REPAIR"
    assert issue_codes == {
        "ORPHAN_FSM_TASK",
        "ORPHAN_ARTIFACT_TASK",
        "ORPHAN_SECTION_TASK",
        "ORPHAN_JOB_TASK",
    }


def test_corrupted_knowledge_index_blocks_task(monkeypatch, tmp_path):
    monkeypatch.setattr("knowledge.store._KB_ROOT", tmp_path)
    knowledge = KnowledgeStore(tmp_path)
    session_id = "reconcile-kb"
    meta = Path(knowledge.session_path(session_id)) / "meta.json"
    meta.write_text("{broken-json", encoding="utf-8")
    orchestration = _orchestration(monkeypatch, knowledge_store=knowledge)
    task_id = _waiting_ring1(orchestration, session_id)

    report = orchestration.reconcile_task_state(task_id).data

    assert report["status"] == "NEEDS_REPAIR"
    assert [issue["code"] for issue in report["issues"]] == ["KB_INDEX_INVALID"]
    with pytest.raises(BizException, match="对账未通过"):
        orchestration.confirm_ring(task_id, 1)
