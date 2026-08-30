# -*- coding: utf-8 -*-
"""作者私有自动草稿的契约测试。

覆盖任务卡第 17 节要求的全部后端场景：单调 revision、大小限制、非法输入、
跨任务/跨租户/跨作者隔离、reviewer/viewer 拒绝、正式提交联动、上游失效、
删除任务清理、ResumeSummary 只返回元数据，以及草稿操作不改变正式状态。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from security import SecuritySettings, SecurityStore
from tests.test_full_flow_hardening import _FlowExecutor
from writing import AutosaveDraftError, AutosaveDraftStore, AutosaveDraftRevisionConflict


# ---------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------
def _settings(db_path=":memory:") -> SecuritySettings:
    return SecuritySettings(
        enabled=True,
        db_path=str(db_path),
        bootstrap_token="bootstrap-token-that-is-at-least-32-characters",
        cookie_name="test_autosave_session",
        cookie_secure=False,
        session_hours=8,
        idle_minutes=30,
    )


def _secured_console(monkeypatch, tmp_path, executor_factory=None):
    """搭建启用安全模式的控制台，返回 (store, app, owner_client, boot, tasks)。"""
    monkeypatch.setenv("THESIS_CORS_ORIGINS", "http://testserver")
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    if executor_factory is not None:
        monkeypatch.setattr(
            "application.service.uc_main_orchestration.get_executor",
            executor_factory,
        )
    store = SecurityStore(settings=_settings(tmp_path / "security.db"))
    app = build_app(orchestration=MainOrchestration(), security_store=store)
    owner = TestClient(app)
    boot = owner.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": store.settings.bootstrap_token},
        json={
            "tenant_name": "草稿租户",
            "username": "draft-owner",
            "password": "draft-owner-strong-pw",
        },
    ).json()
    assert boot["code"] == 0, boot
    assert owner.post(
        "/api/v1/auth/login",
        json={"username": "draft-owner", "password": "draft-owner-strong-pw"},
    ).json()["code"] == 0
    return store, app, owner, boot


def _login_as(app, owner, username, role):
    created = owner.post(
        "/api/v1/auth/users",
        json={
            "username": username,
            "password": f"{username}-strong-pw",
            "role": role,
        },
    ).json()
    assert created["code"] == 0, created
    client = TestClient(app)
    assert client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": f"{username}-strong-pw"},
    ).json()["code"] == 0
    return client


def _new_task(client, title="草稿任务") -> str:
    created = client.post(
        "/api/v1/console/tasks",
        json={"title": title, "degree": "MASTER", "subject_field": "信息管理"},
    ).json()
    assert created["code"] == 0, created
    return created["data"]["task_id"]


def _put_draft(client, task_id, draft_key, payload, revision, **extra):
    return client.put(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/{draft_key}",
        json={
            "object_type": payload.get("object_type", "PROJECT_MEMORY_FORM"),
            "object_id": payload.get("object_id", "new"),
            "stage_no": payload.get("stage_no", 0),
            "base_artifact_id": payload.get("base_artifact_id", ""),
            "base_version": payload.get("base_version", 0),
            "revision": revision,
            "content": payload.get("content", {}),
            **extra,
        },
    ).json()


# ---------------------------------------------------------------------
# 存储层：持久化、revision、大小、生命周期
# ---------------------------------------------------------------------
def test_draft_persists_and_survives_store_reopen(tmp_path):
    path = tmp_path / "autosave.db"
    first = AutosaveDraftStore(path)
    draft = first.save(
        task_id="TASK-1", tenant_id="TEN-1", author_id="USR-1",
        object_type="PROJECT_MEMORY_FORM", draft_key="project-memory:new",
        content={"questions": ["研究问题一"]}, revision=1,
    )
    assert draft.revision == 1
    assert draft.status == "ACTIVE"
    first.close()

    second = AutosaveDraftStore(path)
    restored = second.get("TASK-1", "USR-1", "project-memory:new")
    second.close()
    assert restored is not None
    assert restored.content_json == {"questions": ["研究问题一"]}
    assert restored.revision == 1


def test_each_draft_key_has_independent_revision():
    store = AutosaveDraftStore()
    first = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="ARGUMENT_MAP_FORM",
        draft_key="argument-map:new", content={"title": "甲"}, revision=1,
    )
    second = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="ARGUMENT_MAP_FORM",
        draft_key="argument-map:other", content={"title": "乙"}, revision=1,
    )
    assert first.revision == 1 and second.revision == 1
    bumped = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="ARGUMENT_MAP_FORM",
        draft_key="argument-map:new", content={"title": "甲二"}, revision=2,
    )
    assert bumped.revision == 2
    assert store.get("T", "A", "argument-map:other").revision == 1


def test_out_of_order_write_is_rejected_and_newer_survives():
    store = AutosaveDraftStore()
    store.save(
        task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
        draft_key="section-revision:s1", content={"content": "第一版"}, revision=1,
    )
    store.save(
        task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
        draft_key="section-revision:s1", content={"content": "第二版"}, revision=2,
    )
    with pytest.raises(AutosaveDraftRevisionConflict) as caught:
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="section-revision:s1", content={"content": "旧版迟到"}, revision=1,
        )
    assert caught.value.current_revision == 2
    final = store.get("T", "A", "section-revision:s1")
    assert final.content_json == {"content": "第二版"}


def test_same_revision_same_content_is_idempotent():
    store = AutosaveDraftStore()
    payload = {"content": "同一份内容"}
    first = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
        draft_key="section-revision:s1", content=dict(payload), revision=3,
    )
    replay = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
        draft_key="section-revision:s1", content=dict(payload), revision=3,
    )
    assert replay.revision == 3
    assert replay.updated_at == first.updated_at


def test_same_revision_different_content_conflicts_without_overwrite():
    store = AutosaveDraftStore()
    store.save(
        task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
        draft_key="section-revision:s1", content={"content": "本地"}, revision=4,
    )
    with pytest.raises(AutosaveDraftRevisionConflict):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="section-revision:s1", content={"content": "另一端"}, revision=4,
        )
    assert store.get("T", "A", "section-revision:s1").content_json == {"content": "本地"}


def test_oversized_draft_is_rejected_not_truncated():
    store = AutosaveDraftStore()
    with pytest.raises(AutosaveDraftError, match="字节上限"):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="section-revision:s1",
            content={"content": "甲" * (512 * 1024)}, revision=1,
        )
    assert store.get("T", "A", "section-revision:s1") is None


def test_invalid_object_type_and_draft_key_are_rejected():
    store = AutosaveDraftStore()
    with pytest.raises(AutosaveDraftError):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="NOT_A_TYPE",
            draft_key="whatever:new", content={}, revision=1,
        )
    # 路径穿越
    with pytest.raises(AutosaveDraftError):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="section-revision:../../etc/passwd", content={}, revision=1,
        )
    # 前缀与类型不匹配
    with pytest.raises(AutosaveDraftError):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="project-memory:new", content={}, revision=1,
        )


def test_drafts_are_isolated_across_tasks_and_authors():
    store = AutosaveDraftStore()
    store.save(
        task_id="T1", tenant_id="", author_id="A", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"owner": "A"}, revision=1,
    )
    store.save(
        task_id="T2", tenant_id="", author_id="A", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"owner": "T2"}, revision=1,
    )
    store.save(
        task_id="T1", tenant_id="", author_id="B", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"owner": "B"}, revision=1,
    )
    assert store.get("T1", "A", "project-memory:new").content_json == {"owner": "A"}
    assert store.get("T2", "A", "project-memory:new").content_json == {"owner": "T2"}
    assert store.get("T1", "B", "project-memory:new").content_json == {"owner": "B"}


def test_stale_and_submitted_lifecycle_and_delete_task():
    store = AutosaveDraftStore()
    draft = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 1},
        base_artifact_id="ART-1", base_version=2, revision=1,
    )
    marked = store.mark_stale_by_base("T", "ART-1", current_version=3)
    assert marked == 1
    stale = store.get("T", "A", "project-memory:new")
    assert stale.status == "STALE"
    assert stale.revision == 2
    assert stale.stale_reason
    # 标记过期保留内容，不静默套用
    assert stale.content_json == {"v": 1}

    with pytest.raises(AutosaveDraftError, match="过期草稿"):
        store.mark_submitted(
            "T", "A", "project-memory:new",
            submitted_to_id="ART-9", revision=stale.revision,
        )

    rebased = store.save(
        task_id="T", tenant_id="", author_id="A",
        object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 2},
        base_artifact_id="ART-1", base_version=3, revision=3,
    )
    assert rebased.status == "ACTIVE"
    assert rebased.stale_reason == ""

    submitted = store.mark_submitted(
        "T", "A", "project-memory:new",
        submitted_to_id="ART-9", revision=rebased.revision,
    )
    assert submitted.status == "SUBMITTED"
    assert submitted.revision == 4
    assert submitted.submitted_to_id == "ART-9"
    # 已提交草稿不再作为活动草稿返回
    assert store.list_task("T", "A") == []

    # 已提交内容再次编辑时必须开启新的ACTIVE工作副本。
    reopened = store.save(
        task_id="T", tenant_id="", author_id="A",
        object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 3},
        base_artifact_id="ART-1", base_version=3, revision=5,
    )
    assert reopened.status == "ACTIVE"
    assert reopened.submitted_to_id == ""

    discarded = store.discard(
        "T", "A", "project-memory:new", revision=reopened.revision
    )
    assert discarded.status == "DISCARDED"
    assert discarded.revision == 6
    assert discarded.content_json == {}
    assert store.list_task("T", "A") == []

    # 丢弃墓碑的revision必须拒绝仍在途的旧保存，避免草稿复活。
    with pytest.raises(AutosaveDraftRevisionConflict):
        store.save(
            task_id="T", tenant_id="", author_id="A",
            object_type="PROJECT_MEMORY_FORM",
            draft_key="project-memory:new", content={"v": "old"},
            base_artifact_id="ART-1", base_version=3, revision=5,
        )
    restarted = store.save(
        task_id="T", tenant_id="", author_id="A",
        object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 4},
        base_artifact_id="ART-1", base_version=3, revision=7,
    )
    assert restarted.status == "ACTIVE"
    assert restarted.content_json == {"v": 4}

    store.save(
        task_id="T2", tenant_id="", author_id="A", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 1}, revision=1,
    )
    cleaned = store.delete_task("T2")
    assert cleaned == 1
    assert store.get("T2", "A", "project-memory:new") is None


def test_same_revision_metadata_change_conflicts():
    store = AutosaveDraftStore()
    store.save(
        task_id="T", tenant_id="", author_id="A",
        object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"v": 1},
        stage_no=1, base_artifact_id="ART-1", base_version=1, revision=2,
    )
    with pytest.raises(AutosaveDraftRevisionConflict):
        store.save(
            task_id="T", tenant_id="", author_id="A",
            object_type="PROJECT_MEMORY_FORM",
            draft_key="project-memory:new", content={"v": 1},
            stage_no=1, base_artifact_id="ART-1", base_version=2, revision=2,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("revision", True, "revision必须是整数"),
        ("revision", 9_007_199_254_740_992, "revision必须在"),
        ("stage_no", 11, "stage_no必须在"),
        ("base_version", -1, "base_version不能为负数"),
    ],
)
def test_draft_numeric_bounds(field, value, message):
    store = AutosaveDraftStore()
    payload = {
        "task_id": "T",
        "tenant_id": "",
        "author_id": "A",
        "object_type": "PROJECT_MEMORY_FORM",
        "draft_key": "project-memory:new",
        "content": {"v": 1},
        "revision": 1,
        "stage_no": 0,
        "base_version": 0,
    }
    payload[field] = value
    with pytest.raises(AutosaveDraftError, match=message):
        store.save(**payload)


def test_active_draft_count_limit():
    store = AutosaveDraftStore()
    for index in range(50):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key=f"section-revision:s{index}", content={"i": index}, revision=1,
        )
    with pytest.raises(AutosaveDraftError, match="数量上限"):
        store.save(
            task_id="T", tenant_id="", author_id="A", object_type="SECTION_REVISION",
            draft_key="section-revision:overflow", content={"i": 999}, revision=1,
        )


def test_content_hash_is_recomputed_server_side():
    store = AutosaveDraftStore()
    draft = store.save(
        task_id="T", tenant_id="", author_id="A", object_type="PROJECT_MEMORY_FORM",
        draft_key="project-memory:new", content={"b": 2, "a": 1},
        revision=1, base_version=0,
    )
    import hashlib

    expected = hashlib.sha256(
        json.dumps({"a": 1, "b": 2}, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert draft.content_hash == expected


# ---------------------------------------------------------------------
# API：鉴权、租户、响应内容
# ---------------------------------------------------------------------
def test_list_returns_metadata_only_never_content(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    saved = _put_draft(
        owner, task_id, "project-memory:new",
        {"content": {"questions": ["不得外泄的研究问题正文"]}},
        revision=1,
    )
    assert saved["code"] == 0, saved

    listed = owner.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts"
    ).json()
    assert listed["code"] == 0
    item = listed["data"]["items"][0]
    assert item["draft_key"] == "project-memory:new"
    assert "content_json" not in item
    serialized = json.dumps(listed, ensure_ascii=False)
    assert "不得外泄的研究问题正文" not in serialized

    detail = owner.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/project-memory:new"
    ).json()
    assert detail["code"] == 0
    assert detail["data"]["content_json"] == {"questions": ["不得外泄的研究问题正文"]}


def test_reviewer_and_viewer_cannot_read_or_write_drafts(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    reviewer = _login_as(app, owner, "draft-reviewer", "REVIEWER")
    viewer = _login_as(app, owner, "draft-viewer", "VIEWER")

    assert _put_draft(owner, task_id, "project-memory:new", {"content": {"a": 1}}, 1)["code"] == 0

    for client in (reviewer, viewer):
        base = f"/api/v1/console/tasks/{task_id}/autosave-drafts"
        assert client.get(base).status_code == 403
        assert client.get(f"{base}/project-memory:new").status_code == 403
        assert client.put(f"{base}/project-memory:new", json={"content": {}}).status_code == 403
        assert client.post(f"{base}/project-memory:new/discard").status_code == 403


def test_same_tenant_different_authors_cannot_see_each_other(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    editor_one = _login_as(app, owner, "draft-editor-one", "EDITOR")
    editor_two = _login_as(app, owner, "draft-editor-two", "EDITOR")

    assert _put_draft(editor_one, task_id, "project-memory:new", {"content": {"who": "one"}}, 1)["code"] == 0
    assert _put_draft(editor_two, task_id, "project-memory:new", {"content": {"who": "two"}}, 1)["code"] == 0

    listed_one = editor_one.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts"
    ).json()["data"]["items"]
    listed_two = editor_two.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts"
    ).json()["data"]["items"]
    assert len(listed_one) == 1 and len(listed_two) == 1

    detail_one = editor_one.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/project-memory:new"
    ).json()["data"]["content_json"]
    detail_two = editor_two.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/project-memory:new"
    ).json()["data"]["content_json"]
    assert detail_one == {"who": "one"}
    assert detail_two == {"who": "two"}


def test_draft_key_cannot_cross_tasks(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    first = _new_task(owner, "任务一")
    second = _new_task(owner, "任务二")
    assert _put_draft(owner, first, "project-memory:new", {"content": {"t": "one"}}, 1)["code"] == 0
    assert _put_draft(owner, second, "project-memory:new", {"content": {"t": "two"}}, 1)["code"] == 0

    detail = owner.get(
        f"/api/v1/console/tasks/{second}/autosave-drafts/project-memory:new"
    ).json()["data"]["content_json"]
    assert detail == {"t": "two"}


def test_api_conflict_returns_explicit_conflict_without_overwrite(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    key = "project-memory:new"
    assert _put_draft(owner, task_id, key, {"content": {"v": "server"}}, 1)["code"] == 0
    conflicted = _put_draft(owner, task_id, key, {"content": {"v": "local"}}, 1)
    assert conflicted["code"] != 0
    assert conflicted["data"]["conflict"] is True
    assert conflicted["data"]["current_revision"] == 1
    detail = owner.get(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/{key}"
    ).json()["data"]["content_json"]
    assert detail == {"v": "server"}


def test_deleting_task_clears_drafts(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    assert _put_draft(owner, task_id, "project-memory:new", {"content": {"a": 1}}, 1)["code"] == 0
    assert owner.delete(f"/api/v1/console/tasks/{task_id}").json()["code"] == 0

    other = _new_task(owner, "其它任务")
    listed = owner.get(f"/api/v1/console/tasks/{other}/autosave-drafts").json()
    assert listed["data"]["items"] == []


# ---------------------------------------------------------------------
# 正式状态不受影响
# ---------------------------------------------------------------------
def test_draft_operations_never_change_fsm_artifacts_or_agent_context(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    fake = _FlowExecutor()
    _store, app, owner, _boot = _secured_console(
        monkeypatch, tmp_path, executor_factory=fake.for_ring
    )
    task_id = _new_task(owner)
    orchestration = app.state.orchestration
    before = orchestration.progress(task_id).data
    artifacts_before = len(orchestration.list_artifacts(task_id).data or [])

    key = "project-memory:new"
    assert _put_draft(owner, task_id, key, {"content": {"q": ["问题"]}}, 1)["code"] == 0
    assert _put_draft(owner, task_id, key, {"content": {"q": ["问题二"]}}, 2)["code"] == 0
    assert owner.get(f"/api/v1/console/tasks/{task_id}/autosave-drafts/{key}").json()["code"] == 0
    discarded = owner.post(
        f"/api/v1/console/tasks/{task_id}/autosave-drafts/{key}/discard",
        json={"revision": 2},
    ).json()
    assert discarded["code"] == 0
    assert discarded["data"]["draft"]["status"] == "DISCARDED"
    assert discarded["data"]["draft"]["revision"] == 3

    # 丢弃后的旧在途保存必须被墓碑revision拒绝。
    stale = _put_draft(
        owner, task_id, key, {"content": {"q": ["旧请求"]}}, 2
    )
    assert stale["data"]["conflict"] is True

    after = orchestration.progress(task_id).data
    assert after["phase_state"] == before["phase_state"]
    assert after["current_ring_no"] == before["current_ring_no"]
    assert after["complete_percent"] == before["complete_percent"]
    assert len(orchestration.list_artifacts(task_id).data or []) == artifacts_before
    # 草稿操作不得产生任何后台作业（也就不会调用模型）
    assert orchestration._jobs.list_task(task_id, limit=50) == []  # noqa: SLF001


def test_resume_summary_returns_draft_metadata_only(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    assert _put_draft(
        owner, task_id, "project-memory:new",
        {"content": {"questions": ["绝不外泄的正文内容"]}}, 1,
    )["code"] == 0

    summary = owner.get(f"/api/v1/console/tasks/{task_id}/resume").json()
    assert summary["code"] == 0
    drafts = summary["data"]["autosaved_drafts"]
    assert len(drafts) == 1
    assert drafts[0]["draft_key"] == "project-memory:new"
    assert "content_json" not in drafts[0]

    serialized = json.dumps(summary, ensure_ascii=False)
    assert "绝不外泄的正文内容" not in serialized
    # 能力声明在只有后端时仍如实为 False（M3 接入真实表面后翻正）
    assert summary["data"]["capabilities"]["draft_autosave"] is False


def test_workspace_response_never_contains_draft_content(monkeypatch, tmp_path):
    _store, app, owner, _boot = _secured_console(monkeypatch, tmp_path)
    task_id = _new_task(owner)
    assert _put_draft(
        owner, task_id, "project-memory:new",
        {"content": {"questions": ["工作区响应不得包含正文"]}}, 1,
    )["code"] == 0
    owner.post("/api/v1/console/workspace", json={
        "last_task_id": task_id, "active_tab": "memory",
        "expanded_items": [], "editor_anchor": "", "revision": 1,
    })

    workspace = owner.get("/api/v1/console/workspace").json()
    serialized = json.dumps(workspace, ensure_ascii=False)
    assert "工作区响应不得包含正文" not in serialized
    assert workspace["data"]["resume"]["autosaved_drafts"]
    assert "content_json" not in workspace["data"]["resume"]["autosaved_drafts"][0]
