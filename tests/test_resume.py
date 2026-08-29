"""跨天断点续作的工作区持久化、恢复摘要与API测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration, _TaskStore
from common.aicoding.enums import Degree
from executor.base import ExecResult
from security import SecuritySettings, SecurityStore
from tests.test_full_flow_hardening import _FlowExecutor, _advance_to_ring6


def _flow_orchestration(monkeypatch) -> MainOrchestration:
    """挂载确定性执行体，避免任何真实模型调用。"""
    fake = _FlowExecutor()
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        fake.for_ring,
    )
    return MainOrchestration()


def _rebuilt_orchestration(source: MainOrchestration) -> MainOrchestration:
    """模拟进程重启：新建编排实例，但复用同一批持久化注册表。"""
    return MainOrchestration(
        fsm=source._fsm,  # noqa: SLF001
        docx_renderer=source._docx,  # noqa: SLF001
        store=source._store,  # noqa: SLF001
        artifact_registry=source._artifacts,  # noqa: SLF001
        evidence_ledger=source._evidence,  # noqa: SLF001
        research_registry=source._research,  # noqa: SLF001
        section_registry=source._sections,  # noqa: SLF001
        section_generator=source._section_generator,  # noqa: SLF001
        job_registry=source._jobs,  # noqa: SLF001
        knowledge_store=source._knowledge_store,  # noqa: SLF001
    )


class _DocxCapableFlowExecutor(_FlowExecutor):
    """环6 使用唯一书签，使 docx 交叉引用可生成，从而覆盖环10 完成态。"""

    def for_ring(self, ring_no: int):
        if ring_no != 6:
            return super().for_ring(ring_no)

        class _Ring6:
            def execute(self, _ctx) -> ExecResult:
                # 书签必须落在正文 800 字符之后：摘要取正文前 800 字，
                # 否则同一书签会被定义两次，触发交叉引用重复定义。
                first = (
                    "可信正文内容" * 2500
                    + "[[BOOKMARK:TABLE-1-1|表1-1 结果]] 经用户核验 [RES-TEST] [L1]。"
                )
                second = (
                    "实验分析内容" * 2500
                    + "[[BOOKMARK:TABLE-2-1|表2-1 分析]] 结果复核 [L1]。"
                )
                payload = {
                    "chapters": [
                        {
                            "chapter_no": 1, "chapter_title": "绪论",
                            "content": first, "word_count": len(first),
                        },
                        {
                            "chapter_no": 2, "chapter_title": "实验结果",
                            "content": second, "word_count": len(second),
                        },
                    ],
                    "total_words": len(first) + len(second),
                    "used_refs": ["[L1]"],
                    "used_result_ids": ["RES-TEST"],
                }
                return ExecResult(
                    output=json.dumps(payload, ensure_ascii=False),
                    accept=True,
                    evidence={"source": "test-double"},
                )

        return _Ring6()


def _advance_to_ring8(monkeypatch):
    """把任务推进到环8 已确认，供环9/环10 完成态测试使用。"""
    fake = _DocxCapableFlowExecutor()
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        fake.for_ring,
    )
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration()
    task_id = orchestration.create_task(
        "十环完成", Degree.MASTER, "计算机科学", session_id="resume-delivery"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})
    orchestration.confirm_ring(task_id, 1)
    orchestration.run_ring2(task_id)
    orchestration.confirm_ring(task_id, 2)
    orchestration.run_ring3(task_id)
    orchestration.curate_literature(task_id, {"included_indexes": [0]})
    orchestration.confirm_ring(task_id, 3)
    orchestration.run_ring4(task_id)
    orchestration.confirm_ring(task_id, 4)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    orchestration.run_ring6(task_id)
    orchestration.confirm_ring(task_id, 6)
    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    orchestration.run_ring8(task_id)
    orchestration.confirm_ring(task_id, 8)
    return orchestration, fake, task_id


def _secured_console(monkeypatch, tmp_path):
    """搭建启用安全模式的控制台，返回 (store, app, owner_client, boot)。"""
    monkeypatch.setenv("THESIS_CORS_ORIGINS", "http://testserver")
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    store = SecurityStore(settings=SecuritySettings(
        enabled=True,
        db_path=str(tmp_path / "resume-security.db"),
        bootstrap_token="bootstrap-token-that-is-at-least-32-characters",
        cookie_name="test_resume_session",
        cookie_secure=False,
        session_hours=8,
        idle_minutes=30,
    ))
    app = build_app(orchestration=MainOrchestration(), security_store=store)
    owner = TestClient(app)
    boot = owner.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": store.settings.bootstrap_token},
        json={
            "tenant_name": "Resume Tenant",
            "username": "owner-resume",
            "password": "owner-resume-strong-password",
        },
    ).json()
    assert boot["code"] == 0, boot
    assert owner.post(
        "/api/v1/auth/login",
        json={
            "username": "owner-resume",
            "password": "owner-resume-strong-password",
        },
    ).json()["code"] == 0
    return store, app, owner, boot


def _login_as(app, owner, username, role):
    """在同一租户内创建并登录一个指定角色的用户。"""
    created = owner.post(
        "/api/v1/auth/users",
        json={
            "username": username,
            "password": f"{username}-strong-password",
            "role": role,
        },
    ).json()
    assert created["code"] == 0, created
    client = TestClient(app)
    assert client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": f"{username}-strong-password",
        },
    ).json()["code"] == 0
    return client


class _Ring1Executor:
    def execute(self, _ctx) -> ExecResult:
        return ExecResult(
            output=json.dumps({
                "candidates": [
                    {"title": "可恢复论文任务", "innovation": "断点续作"},
                    {"title": "可审计论文任务", "innovation": "恢复摘要"},
                ],
                "recommendation": "选择候选题目",
            }, ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


def test_workspace_state_survives_store_reopen(tmp_path):
    path = tmp_path / "task-store.db"
    first = _TaskStore(path)
    stored = first.put_workspace("local:default", {
        "last_task_id": "TASK-1",
        "active_tab": "memory",
        "expanded_items": ["memory-builder"],
        "editor_anchor": "section-1.2",
    })
    assert stored["updated_at"]
    first._db.close()  # noqa: SLF001 - 模拟进程结束

    second = _TaskStore(path)
    restored = second.get_workspace("local:default")
    second._db.close()  # noqa: SLF001

    assert restored["last_task_id"] == "TASK-1"
    assert restored["active_tab"] == "memory"
    assert restored["expanded_items"] == ["memory-builder"]
    assert restored["editor_anchor"] == "section-1.2"


def test_resume_summary_exposes_only_next_safe_action(monkeypatch):
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda _ring_no: _Ring1Executor(),
    )
    orchestration = MainOrchestration()
    task_id = orchestration.create_task(
        "断点续作", Degree.MASTER, "人工智能", session_id="resume-summary"
    ).data["task_id"]

    initial = orchestration.get_resume_summary(task_id).data
    assert initial["next_safe_action"]["type"] == "EXECUTE_RING"

    orchestration.run_ring1(task_id)
    waiting = orchestration.get_resume_summary(task_id).data
    assert waiting["phase_state"] == "WAITING_APPROVAL"
    assert waiting["next_safe_action"]["type"] == "COMPLETE_AUTHOR_DECISION"
    assert waiting["pending_approvals"][0]["type"] == "RING_GATE"

    orchestration.select_ring1_candidate(task_id, {"candidate_index": 0})
    ready = orchestration.get_resume_summary(task_id).data
    assert ready["next_safe_action"]["type"] == "CONFIRM_RING"
    assert ready["autosaved_drafts"] == []
    assert ready["capabilities"]["draft_autosave"] is False


def test_workspace_console_api_returns_resume_summary(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration()
    task = orchestration.create_task(
        "继续上次论文", Degree.BACHELOR, "信息管理", session_id="resume-api"
    ).data
    client = TestClient(build_app(orchestration=orchestration))

    saved = client.post(
        "/api/v1/console/workspace",
        json={
            "last_task_id": task["task_id"],
            "active_tab": "evidence",
            "expanded_items": [],
            "editor_anchor": "",
        },
    ).json()
    restored = client.get("/api/v1/console/workspace").json()
    summary = client.get(
        f"/api/v1/console/tasks/{task['task_id']}/resume?session_id=resume-api"
    ).json()

    assert saved["code"] == 0
    assert restored["data"]["workspace"]["active_tab"] == "evidence"
    assert restored["data"]["resume"]["task_id"] == task["task_id"]
    assert restored["data"]["resume"]["next_safe_action"]["type"] == "EXECUTE_RING"
    assert summary["data"]["consistency_status"] == "CONSISTENT"


def test_invalid_workspace_payload_is_rejected_and_keeps_previous_state(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration()
    task = orchestration.create_task(
        "工作区校验", Degree.BACHELOR, "信息管理", session_id="resume-validation"
    ).data
    client = TestClient(build_app(orchestration=orchestration))

    good = {
        "last_task_id": task["task_id"],
        "active_tab": "writing",
        "expanded_items": ["section-1"],
        "editor_anchor": "section-1.1",
    }
    assert client.post("/api/v1/console/workspace", json=good).json()["code"] == 0

    invalid_payloads = [
        {"last_task_id": task["task_id"], "active_tab": "not-a-tab"},
        {"last_task_id": "X" * 200, "active_tab": "writing"},
        {
            "last_task_id": task["task_id"],
            "active_tab": "writing",
            "expanded_items": [f"item-{index}" for index in range(40)],
        },
        {
            "last_task_id": task["task_id"],
            "active_tab": "writing",
            "editor_anchor": "A" * 500,
        },
        {"last_task_id": task["task_id"], "active_tab": "writing", "extra": 1},
    ]
    for payload in invalid_payloads:
        response = client.post("/api/v1/console/workspace", json=payload).json()
        assert response["code"] != 0, payload

    restored = client.get("/api/v1/console/workspace").json()["data"]["workspace"]
    assert restored["last_task_id"] == task["task_id"]
    assert restored["active_tab"] == "writing"
    assert restored["expanded_items"] == ["section-1"]
    assert restored["editor_anchor"] == "section-1.1"


def test_deleting_task_clears_every_workspace_position_field(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration()
    task = orchestration.create_task(
        "待删除论文", Degree.MASTER, "教育学", session_id="resume-delete"
    ).data
    client = TestClient(build_app(orchestration=orchestration))
    client.post(
        "/api/v1/console/workspace",
        json={
            "last_task_id": task["task_id"],
            "active_tab": "jobs",
            "expanded_items": ["job-1"],
            "editor_anchor": "section-2.3",
        },
    )

    assert client.delete(
        f"/api/v1/console/tasks/{task['task_id']}"
    ).json()["code"] == 0

    workspace = client.get("/api/v1/console/workspace").json()["data"]["workspace"]
    assert workspace["last_task_id"] == ""
    assert workspace["active_tab"] == "refs"
    assert workspace["expanded_items"] == []
    assert workspace["editor_anchor"] == ""


def test_workspace_self_heals_when_last_task_vanishes(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration()
    client = TestClient(build_app(orchestration=orchestration))

    # 直接写入一个指向不存在任务的工作区，模拟任务被外部删除后的残留指针。
    orchestration._store.put_workspace(  # noqa: SLF001 - 构造残留指针
        "local:default",
        {
            "last_task_id": "TASK-DOES-NOT-EXIST",
            "active_tab": "jobs",
            "expanded_items": [],
            "editor_anchor": "",
        },
    )
    healed = client.get("/api/v1/console/workspace").json()["data"]
    assert healed["workspace"]["last_task_id"] == ""
    assert healed["workspace"]["active_tab"] == "refs"
    assert healed["resume"] is None

    # 自愈结果必须落盘，下一次读取不能再次返回幽灵指针。
    again = client.get("/api/v1/console/workspace").json()["data"]
    assert again["workspace"]["last_task_id"] == ""


def test_resume_summary_survives_orchestration_rebuild(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        _FlowExecutor().for_ring,
    )
    first = MainOrchestration()
    task_id = first.create_task(
        "重启恢复", Degree.MASTER, "计算机科学", session_id="resume-rebuild"
    ).data["task_id"]
    first.run_ring1(task_id)
    first.select_ring1_candidate(task_id, {"candidate_index": 1})
    first.save_workspace_state(
        "local:default",
        {"last_task_id": task_id, "active_tab": "memory", "expanded_items": []},
    )

    # 模拟进程重启：新建编排实例，复用同一批持久化注册表。
    second = _rebuilt_orchestration(first)
    assert second.get_workspace_state("local:default").data["workspace"][
        "active_tab"
    ] == "memory"

    resume = second.get_resume_summary(task_id).data
    assert resume["task_id"] == task_id
    assert resume["current_ring_no"] == 1
    assert resume["phase_state"] == "WAITING_APPROVAL"
    assert resume["next_safe_action"]["type"] == "CONFIRM_RING"


def test_waiting_approval_is_not_auto_approved_after_restart(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        _FlowExecutor().for_ring,
    )
    first = MainOrchestration()
    task_id = first.create_task(
        "待审批不自动放行", Degree.MASTER, "计算机科学", session_id="resume-approval"
    ).data["task_id"]
    first.run_ring1(task_id)
    first.select_ring1_candidate(task_id, {"candidate_index": 1})
    pending_before = first.get_resume_summary(task_id).data
    assert pending_before["phase_state"] == "WAITING_APPROVAL"
    assert pending_before["pending_approvals"]

    second = _rebuilt_orchestration(first)
    pending_after = second.get_resume_summary(task_id).data
    # 重启后仍是待审批：不自动批准、不自动重跑。
    assert pending_after["phase_state"] == "WAITING_APPROVAL"
    assert pending_after["current_ring_no"] == 1
    assert pending_after["pending_approvals"] == pending_before["pending_approvals"]
    assert pending_after["next_safe_action"]["type"] == "CONFIRM_RING"
    assert not pending_after["active_jobs"]


def test_next_safe_action_covers_execute_confirm_and_author_decision(monkeypatch):
    orchestration = _flow_orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "动作路由", Degree.BACHELOR, "信息管理", session_id="resume-actions"
    ).data["task_id"]

    assert orchestration.get_resume_summary(
        task_id
    ).data["next_safe_action"]["type"] == "EXECUTE_RING"

    orchestration.run_ring1(task_id)
    author_decision = orchestration.get_resume_summary(task_id).data
    assert author_decision["next_safe_action"]["type"] == "COMPLETE_AUTHOR_DECISION"
    assert author_decision["pending_approvals"][0]["type"] == "RING_GATE"

    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})
    assert orchestration.get_resume_summary(
        task_id
    ).data["next_safe_action"]["type"] == "CONFIRM_RING"


def test_next_safe_action_reports_recover_stage_after_rejection(monkeypatch):
    orchestration = _flow_orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "退回恢复", Degree.BACHELOR, "信息管理", session_id="resume-fallback"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})

    rejected = orchestration.confirm_ring(task_id, 1, confirmed=False,
                                          reject_reason="需要重新选题")
    assert rejected.is_ok
    resume = orchestration.get_resume_summary(task_id).data
    assert resume["phase_state"] == "FALLBACK"
    assert resume["next_safe_action"]["type"] == "RECOVER_STAGE"


def test_next_safe_action_reports_monitor_job_for_active_job(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = _flow_orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "后台作业", Degree.MASTER, "计算机科学", session_id="resume-jobs"
    ).data["task_id"]

    job = orchestration._jobs.create(  # noqa: SLF001 - 构造活动作业
        task_id=task_id,
        session_id="resume-jobs",
        operation="ring.execute",
        payload={"ring_no": 1},
        max_attempts=1,
    )
    resume = orchestration.get_resume_summary(task_id).data
    assert resume["next_safe_action"]["type"] == "MONITOR_JOB"
    assert resume["next_safe_action"]["job_id"] == job.job_id
    assert resume["active_jobs"][0]["job_id"] == job.job_id
    assert resume["active_jobs"][0]["operation"] == "ring.execute"


def test_next_safe_action_reports_repair_required_when_projection_pending(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = _flow_orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "一致性阻断", Degree.MASTER, "计算机科学", session_id="resume-repair"
    ).data["task_id"]

    # 故障注入：产物投影未完成时，恢复必须停在修复入口而不是继续推进。
    monkeypatch.setattr(
        orchestration,
        "_project_pending_artifacts",
        lambda _task_id: ["outbox:unprojected"],
    )
    resume = orchestration.get_resume_summary(task_id).data
    assert resume["consistency_status"] == "NEEDS_REPAIR"
    assert resume["consistency_issues"] == ["outbox:unprojected"]
    assert resume["next_safe_action"]["type"] == "REPAIR_REQUIRED"


def test_next_safe_action_reaches_review_delivery(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration, _fake, task_id = _advance_to_ring8(monkeypatch)
    assert orchestration.generate_docx(task_id).is_ok
    orchestration.run_ring9(task_id)
    orchestration.confirm_ring(task_id, 9)
    orchestration.run_ring10(task_id)
    orchestration.confirm_ring(task_id, 10)

    resume = orchestration.get_resume_summary(task_id).data
    assert resume["complete_percent"] >= 100
    assert resume["next_safe_action"]["type"] == "REVIEW_DELIVERY"


def test_resume_summary_exposes_no_body_draft_payload_or_secret(monkeypatch):
    orchestration = _flow_orchestration(monkeypatch)
    task_id = orchestration.create_task(
        "敏感字段检查", Degree.MASTER, "计算机科学", session_id="resume-secret"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})
    orchestration._jobs.create(  # noqa: SLF001 - 构造作业以覆盖作业字段
        task_id=task_id,
        session_id="resume-secret",
        operation="ring.execute",
        payload={"ring_no": 1, "note": "作业内部载荷不得外泄"},
        max_attempts=1,
    )

    resume = orchestration.get_resume_summary(task_id).data
    serialized = json.dumps(resume, ensure_ascii=False)

    assert set(resume) == {
        "task_id", "title", "current_ring_no", "current_ring", "phase_state",
        "complete_percent", "last_approved_artifact", "pending_approvals",
        "active_jobs", "recoverable_jobs", "autosaved_drafts",
        "consistency_status", "consistency_issues", "next_safe_action",
        "capabilities",
    }
    for job in [*resume["active_jobs"], *resume["recoverable_jobs"]]:
        assert set(job) == {
            "job_id", "operation", "status", "attempt", "max_attempts",
            "tokens_used", "token_budget", "updated_at",
        }
    for forbidden in (
        "content", "body", "payload", "api_key", "apiKey", "sk-",
        "file_content", "prompt", "draft_text", "作业内部载荷不得外泄",
    ):
        assert forbidden not in serialized


def test_cross_tenant_workspace_pointer_is_rejected():
    orchestration = MainOrchestration()
    foreign = orchestration.create_task(
        "其他租户论文", Degree.BACHELOR, "信息管理",
        session_id="foreign", tenant_id="tenant-b",
    ).data

    with pytest.raises(PermissionError):
        orchestration.save_workspace_state(
            "tenant-a:user-1",
            {"last_task_id": foreign["task_id"], "active_tab": "refs"},
            tenant_id="tenant-a",
        )

    # 被拒绝的写入不得留下任何残留状态。
    stored = orchestration.get_workspace_state(
        "tenant-a:user-1", tenant_id="tenant-a"
    ).data
    assert stored["workspace"]["last_task_id"] == ""

    # 读取路径同样不能把其他租户的任务带进当前工作区。
    orchestration._store.put_workspace(  # noqa: SLF001 - 构造越权残留指针
        "tenant-a:user-1",
        {
            "last_task_id": foreign["task_id"],
            "active_tab": "jobs",
            "expanded_items": [],
            "editor_anchor": "",
        },
    )
    healed = orchestration.get_workspace_state(
        "tenant-a:user-1", tenant_id="tenant-a"
    ).data
    assert healed["workspace"]["last_task_id"] == ""
    assert healed["resume"] is None


def test_workspaces_are_isolated_between_users_of_same_tenant(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    first_task = owner.post(
        "/api/v1/console/tasks",
        json={
            "title": "用户一论文", "degree": "MASTER",
            "subject_field": "AI",
        },
    ).json()["data"]["task_id"]
    second_task = owner.post(
        "/api/v1/console/tasks",
        json={
            "title": "用户二论文", "degree": "MASTER",
            "subject_field": "AI",
        },
    ).json()["data"]["task_id"]
    user_one = _login_as(app, owner, "resume-user-one", "EDITOR")
    user_two = _login_as(app, owner, "resume-user-two", "EDITOR")

    assert user_one.post(
        "/api/v1/console/workspace",
        json={
            "last_task_id": first_task,
            "active_tab": "writing",
            "expanded_items": [],
            "editor_anchor": "",
        },
    ).json()["code"] == 0
    assert user_two.post(
        "/api/v1/console/workspace",
        json={
            "last_task_id": second_task,
            "active_tab": "evidence",
            "expanded_items": [],
            "editor_anchor": "",
        },
    ).json()["code"] == 0

    one = user_one.get("/api/v1/console/workspace").json()["data"]["workspace"]
    two = user_two.get("/api/v1/console/workspace").json()["data"]["workspace"]
    assert one["last_task_id"] == first_task
    assert one["active_tab"] == "writing"
    assert two["last_task_id"] == second_task
    assert two["active_tab"] == "evidence"


def test_viewer_can_save_own_position_but_cannot_advance_fsm(
    monkeypatch, tmp_path,
):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = owner.post(
        "/api/v1/console/tasks",
        json={
            "title": "只读角色论文", "degree": "MASTER",
            "subject_field": "AI",
        },
    ).json()["data"]["task_id"]
    owner.post(
        f"/api/v1/console/tasks/{task_id}/rings/1/execute", json={}
    )
    owner.post(
        f"/api/v1/console/tasks/{task_id}/rings/1/select",
        json={"candidate_index": 0},
    )
    viewer = _login_as(app, owner, "resume-viewer", "VIEWER")

    # 工作区位置是私有偏好：viewer 可以保存自己的页面位置。
    saved = viewer.post(
        "/api/v1/console/workspace",
        json={
            "last_task_id": task_id,
            "active_tab": "memory",
            "expanded_items": [],
            "editor_anchor": "",
        },
    )
    assert saved.json()["code"] == 0, saved.json()
    assert viewer.get("/api/v1/console/workspace").json()[
        "data"
    ]["workspace"]["active_tab"] == "memory"

    # 但绝不意味着 viewer 能借工作区推进 FSM 或审批产物。
    assert viewer.post(
        f"/api/v1/console/tasks/{task_id}/rings/1/confirm", json={}
    ).status_code == 403
    assert viewer.post(
        "/api/v1/console/tasks",
        json={
            "title": "只读角色不得建任务", "degree": "MASTER",
            "subject_field": "AI",
        },
    ).status_code == 403

    progress = owner.get(
        f"/api/v1/console/tasks/{task_id}/progress"
    ).json()
    assert progress["code"] == 0
    assert progress["data"]["phase_state"] == "WAITING_APPROVAL"
