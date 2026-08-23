"""FSM 事务 Outbox 与应用编排的恢复测试。"""

from __future__ import annotations

import json

from artifacts import ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from executor.base import ExecResult


class _Executor:
    def __init__(self, ring_no: int) -> None:
        self.ring_no = int(ring_no)

    def execute(self, ctx) -> ExecResult:
        payload = (
            {
                "candidates": [{"title": "证据可追溯的论文智能体研究"}],
                "recommendation": "推荐",
            }
            if self.ring_no == 1
            else {
                "novelty_level": "HIGH",
                "similar_count": 0,
                "recommendation": "通过",
            }
        )
        return ExecResult(
            output=json.dumps(payload, ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


def _orchestration(monkeypatch) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Executor(int(ring_no)),
    )
    return MainOrchestration(artifact_registry=ArtifactRegistry())


def test_confirm_projects_versioned_artifact(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    created = orchestration.create_task(
        "论文智能体", Degree.MASTER, "计算机科学", session_id="outbox-1"
    )
    task_id = created.data["task_id"]
    orchestration.run_ring1(task_id)
    confirmed = orchestration.confirm_ring(task_id, 1)
    assert confirmed.is_ok
    assert confirmed.data["artifact_projection_pending"] is False

    artifacts = orchestration.list_artifacts(task_id).data
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "TOPIC_PROPOSAL"
    assert artifacts[0]["status"] == "APPROVED"
    assert artifacts[0]["source_event_id"].startswith("EVT-")

    state = orchestration._fsm.get_task(task_id)
    event = state.aux_artifacts["artifact_outbox"][0]
    assert event["projection_status"] == "PROJECTED"
    assert event["artifact_id"] == artifacts[0]["artifact_id"]


def test_projection_failure_is_recovered_from_durable_outbox(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "恢复测试", Degree.MASTER, "计算机科学", session_id="outbox-2"
    ).data["task_id"]
    orchestration.run_ring1(task_id)

    original_project = orchestration._artifact_projector.project

    def fail_once(event):
        raise RuntimeError("temporary projection failure")

    monkeypatch.setattr(orchestration._artifact_projector, "project", fail_once)
    confirmed = orchestration.confirm_ring(task_id, 1)
    assert confirmed.is_ok
    assert confirmed.data["current_ring_no"] == 2
    assert confirmed.data["artifact_projection_pending"] is True
    assert orchestration._fsm.get_task(task_id).aux_artifacts["artifact_outbox"][0][
        "projection_status"
    ] == "PENDING"

    monkeypatch.setattr(orchestration._artifact_projector, "project", original_project)
    progress = orchestration.progress(task_id)
    assert progress.data["artifact_projection_pending"] is False
    assert orchestration.list_artifacts(task_id).data[0]["status"] == "APPROVED"


def test_rejected_stage_is_recorded_without_advancing(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "驳回测试", Degree.MASTER, "计算机科学", session_id="outbox-3"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    rejected = orchestration.confirm_ring(task_id, 1, confirmed=False, reject_reason="方向过宽")
    assert rejected.is_ok
    assert rejected.data["current_ring_no"] == 1
    assert rejected.data["phase_state"] == "FALLBACK"
    artifacts = orchestration.list_artifacts(task_id).data
    assert artifacts[0]["status"] == "REJECTED"


def test_approved_upstream_revision_marks_downstream_stale(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "版本传播", Degree.MASTER, "计算机科学", session_id="outbox-4"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.confirm_ring(task_id, 1)
    orchestration.run_ring2(task_id)
    orchestration.confirm_ring(task_id, 2)

    before = orchestration.list_artifacts(task_id).data
    ring1_v1 = next(item for item in before if item["stage_no"] == 1)
    ring2_v1 = next(item for item in before if item["stage_no"] == 2)
    assert ring2_v1["dependency_ids"] == [ring1_v1["artifact_id"]]

    orchestration._fsm.rollback(task_id, 1)
    orchestration.run_ring1(task_id)
    orchestration.confirm_ring(task_id, 1)
    after = orchestration.list_artifacts(task_id).data
    old_ring1 = next(item for item in after if item["artifact_id"] == ring1_v1["artifact_id"])
    old_ring2 = next(item for item in after if item["artifact_id"] == ring2_v1["artifact_id"])
    assert old_ring1["status"] == "SUPERSEDED"
    assert old_ring2["status"] == "STALE"

    outbox = orchestration._fsm.get_task(task_id).aux_artifacts["artifact_outbox"]
    assert len(outbox) == 3
    assert all(event["projection_status"] == "PROJECTED" for event in outbox)


def test_pending_projection_survives_process_restart(tmp_path, monkeypatch):
    from application.service.uc_main_orchestration import _TaskStore
    from fsm.orchestrator import FsmOrchestrator
    from fsm.repository import SqlAlchemyFsmRepository
    from fsm.state.orm import FSMBase
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Executor(int(ring_no)),
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'fsm.db'}")
    FSMBase.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    task_db = str(tmp_path / "tasks.db")
    artifact_db = tmp_path / "artifacts.db"

    first = MainOrchestration(
        fsm=FsmOrchestrator(SqlAlchemyFsmRepository(sessions)),
        store=_TaskStore(db_path=task_db),
        artifact_registry=ArtifactRegistry(artifact_db),
    )
    task_id = first.create_task(
        "重启恢复", Degree.MASTER, "计算机科学", session_id="outbox-restart"
    ).data["task_id"]
    first.run_ring1(task_id)
    monkeypatch.setattr(
        first._artifact_projector,
        "project",
        lambda event: (_ for _ in ()).throw(RuntimeError("simulated crash")),
    )
    first.confirm_ring(task_id, 1)

    second = MainOrchestration(
        fsm=FsmOrchestrator(SqlAlchemyFsmRepository(sessions)),
        store=_TaskStore(db_path=task_db),
        artifact_registry=ArtifactRegistry(artifact_db),
    )
    progress = second.progress(task_id)
    assert progress.data["current_ring_no"] == 2
    assert progress.data["artifact_projection_pending"] is False
    assert second.list_artifacts(task_id).data[0]["status"] == "APPROVED"


def test_artifact_versions_are_exposed_by_console_api(monkeypatch):
    from application.main import build_app
    from fastapi.testclient import TestClient

    app = build_app(orchestration=_orchestration(monkeypatch))
    client = TestClient(app)
    created = client.post(
        "/api/v1/console/tasks",
        json={
            "title": "API产物测试",
            "degree": "MASTER",
            "subject_field": "计算机科学",
            "session_id": "outbox-api",
        },
    ).json()
    task_id = created["data"]["task_id"]
    client.post(
        f"/api/v1/console/tasks/{task_id}/rings/1/execute?session_id=outbox-api"
    )
    client.post(
        f"/api/v1/console/tasks/{task_id}/rings/1/confirm?session_id=outbox-api",
        json={"confirmed": True},
    )
    response = client.get(
        f"/api/v1/console/tasks/{task_id}/artifacts?session_id=outbox-api"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"][0]["kind"] == "TOPIC_PROPOSAL"
    assert body["data"][0]["status"] == "APPROVED"
