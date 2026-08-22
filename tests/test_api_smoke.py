# -*- coding: utf-8 -*-
"""FastAPI 最小闭环烟雾测试（不依赖数据库，内存态）。"""
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
