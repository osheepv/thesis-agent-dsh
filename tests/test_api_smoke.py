# -*- coding: utf-8 -*-
"""FastAPI 最小闭环烟雾测试（任务API共享持久化编排）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from application.app import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "UP"


def test_create_task():
    r = client.post(
        "/api/v1/tasks",
        json={"title": "基于大模型的论文写作研究", "degree": "MASTER", "discipline": "计算机科学与技术"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["task_id"]
    assert body["data"]["status"] == "NOT_STARTED"
    assert body["data"]["current_ring"] == "RING_1"


def test_list_tasks_after_create():
    r = client.post(
        "/api/v1/tasks",
        json={"title": "测试任务", "degree": "BACHELOR"},
    )
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]

    r2 = client.get("/api/v1/tasks")
    assert r2.status_code == 200
    body = r2.json()
    assert body["code"] == 0
    assert body["data"]["total"] >= 1
    assert any(t["task_id"] == task_id for t in body["data"]["items"])


def test_get_task_not_found():
    r = client.get("/api/v1/tasks/not-exist-id")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 100001


def test_native_and_console_task_apis_share_one_record():
    created = client.post(
        "/api/v1/tasks",
        json={
            "title": "统一任务事实源",
            "degree": "BACHELOR",
            "discipline": "计算机科学",
            "session_id": "shared-task-api",
        },
    ).json()
    task_id = created["data"]["task_id"]

    console_items = client.get(
        "/api/v1/console/tasks", params={"session_id": "shared-task-api"}
    ).json()["data"]
    native_detail = client.get(f"/api/v1/tasks/{task_id}").json()["data"]

    assert [item["task_id"] for item in console_items] == [task_id]
    assert native_detail["task_id"] == task_id
    assert native_detail["current_ring"] == "RING_1"
    assert native_detail["discipline"] == "计算机科学"
