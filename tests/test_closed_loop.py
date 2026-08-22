# -*- coding: utf-8 -*-
"""主编排闭环端到端测试。

覆盖「创建论文任务 → 环1选题 → 环5大纲 → 环6撰写 → 生成 docx」六步闭环：
    1. 创建任务（FSM 初始化，停在环1）
    2. 推进环1选题（M2 出候选题目，FSM 推进到环2）
    3. 推进环5大纲（M2 出章节结构，FSM 推进到环6）
    4. 推进环6撰写（M2 出初稿正文，FSM 推进到环7）
    5. 生成 docx（M5/M6 渲染端口，返回下载链接）
    6. 进度视图（委托 M1 progress）

同名冲突已通过业务包重命名（backend.docx -> backend.thesis_docx）解决；本测试
仍以 MainOrchestration 直连 + 注入 mock docx 渲染端口为主，避免单测依赖真实
docxtpl/libreoffice 渲染，另附一个基于 TestClient 的 HTTP 级闭环（仅走
WriterConsole，不走 M1/M5/M6 原生路由）。真实链路（不注入 mock）在上层手工验证。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from common.aicoding.enums import Degree
from application.service.uc_main_orchestration import MainOrchestration


# ---------------------------------------------------------------------
# Mock docx 渲染端口（_TaskStore 重命名后不再引用，保留 import 兼容）
# ---------------------------------------------------------------------
class MockDocxRenderer:
    """docx 渲染 mock：返回确定性的占位符与下载链接。"""

    def upload_template(self, file_bytes: bytes, filename: str, **meta) -> dict:
        return {
            "template_id": meta.get("template_id", "TPL-MOCK"),
            "filename": filename,
            "placeholders": ["topic", "outline", "chapter"],
            "section_count": 3,
        }

    def generate(self, template_id: str, content: dict, **meta) -> dict:
        word_count = sum(len(v) for v in content.values() if isinstance(v, str))
        return {
            "file_id": f"FILE-{template_id}",
            "download_url": "/api/v1/docx/files/thesis.docx",
            "filename": "thesis.docx",
            "word_count": word_count,
        }


@pytest.fixture()
def orchestration() -> MainOrchestration:
    """主编排用例（注入 mock docx 渲染端口，FSM/executor 使用真实内存实现）。"""
    return MainOrchestration(docx_renderer=MockDocxRenderer())


# ---------------------------------------------------------------------
# 端到端闭环（直连 orchestration）
# ---------------------------------------------------------------------
def test_full_closed_loop(orchestration: MainOrchestration):
    # 1. 创建任务
    r = orchestration.create_task(
        title="基于深度学习的图像识别研究",
        degree=Degree.MASTER,
        subject_field="计算机视觉",
        session_id="sess-test-1",
    )
    assert r.is_ok
    task_id = r.data["task_id"]
    assert task_id

    # 2. 环1 选题
    r1 = orchestration.run_ring1(task_id)
    assert r1.is_ok, r1.msg
    assert r1.data["candidates"]
    assert r1.data["chosen"]

    # 3. 环5 大纲
    r5 = orchestration.run_ring5(task_id)
    assert r5.is_ok, r5.msg
    assert r5.data["outline"]
    assert r5.data["chapters"]

    # 4. 环6 撰写
    r6 = orchestration.run_ring6(task_id)
    assert r6.is_ok, r6.msg
    assert r6.data["chapters"]
    assert r6.data["total_words"] > 0
    # 一期内 mock 字数按学位区分（硕士 > 本科）
    # 这里仅断言存在正数内容
    assert r6.data["content_preview"]

    # 5. 生成 docx
    rd = orchestration.generate_docx(task_id)
    assert rd.is_ok, rd.msg
    assert rd.data["download_url"]
    assert rd.data["file_id"]

    # 6. 进度：FSM 应推进到环7（环6已通过）
    rp = orchestration.progress(task_id)
    assert rp.is_ok, rp.msg
    assert rp.data["current_ring_no"] >= 7
    rings = rp.data["rings"]
    ring6 = next(x for x in rings if x["ring_no"] == 6)
    assert ring6["state"] == "PASSED"


def test_progress_advances_per_step(orchestration: MainOrchestration):
    """验证 FSM 状态随环节推进逐步演进。"""
    r = orchestration.create_task("测试进度", Degree.BACHELOR, "数据挖掘", session_id="sess-2")
    tid = r.data["task_id"]
    assert orchestration.progress(tid).data["current_ring_no"] == 1
    orchestration.run_ring1(tid)
    assert orchestration.progress(tid).data["current_ring_no"] >= 2
    orchestration.run_ring5(tid)
    assert orchestration.progress(tid).data["current_ring_no"] >= 6
    orchestration.run_ring6(tid)
    assert orchestration.progress(tid).data["current_ring_no"] >= 7


def test_session_guard_rejects_foreign_session(orchestration: MainOrchestration):
    """会话隔离：非归属会话不能访问任务。"""
    r = orchestration.create_task("会话隔离", Degree.MASTER, "NLP", session_id="sess-a")
    tid = r.data["task_id"]
    # 归属会话可访问
    orchestration.assert_session(tid, "sess-a")
    # 非归属会话应拒绝
    from common.aicoding.exception import BizException, ErrorCode

    with pytest.raises(BizException) as exc:
        orchestration.assert_session(tid, "sess-b")
    assert exc.value.code == ErrorCode.FORBIDDEN.value


def test_task_not_found(orchestration: MainOrchestration):
    """不存在任务抛 TASK_NOT_FOUND。"""
    from common.aicoding.exception import BizException, ErrorCode

    with pytest.raises(BizException) as exc:
        orchestration.run_ring1("no-such-task")
    assert exc.value.code == ErrorCode.TASK_NOT_FOUND.value


# ---------------------------------------------------------------------
# HTTP 级闭环（TestClient，仅走 WriterConsole）
# ---------------------------------------------------------------------
@pytest.fixture()
def client() -> TestClient:
    from application.main import build_app

    app = build_app(orchestration=MainOrchestration(docx_renderer=MockDocxRenderer()))
    return TestClient(app)


def test_http_closed_loop(client: TestClient):
    """通过聚合路由跑闭环，断言每步 Result.code == 0。"""
    r = client.post("/api/v1/console/tasks", json={
        "title": "HTTP闭环-基于大模型的推荐研究",
        "degree": "MASTER",
        "subject_field": "推荐系统",
        "session_id": "sess-http",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    tid = body["data"]["task_id"]

    steps = [
        ("/rings/1/execute", {}),
        ("/rings/5/outline", {}),
        ("/rings/6/chapter", {}),
        ("/docx/generate", {}),
    ]
    for path, _ in steps:
        rr = client.post(f"/api/v1/console/tasks/{tid}{path}?session_id=sess-http")
        assert rr.status_code == 200
        assert rr.json()["code"] == 0, f"{path}: {rr.text}"

    # 进度
    rp = client.get(f"/api/v1/console/tasks/{tid}/progress?session_id=sess-http")
    assert rp.status_code == 200
    data = rp.json()["data"]
    assert data["current_ring_no"] >= 7


def test_http_session_guard(client: TestClient):
    """HTTP 会话隔离：错误 session 返回非 0 code。"""
    r = client.post("/api/v1/console/tasks", json={
        "title": "会话隔离测试", "degree": "MASTER", "subject_field": "CV",
        "session_id": "sess-a",
    })
    tid = r.json()["data"]["task_id"]
    r2 = client.post(f"/api/v1/console/tasks/{tid}/rings/1/execute?session_id=sess-b")
    assert r2.status_code == 200
    assert r2.json()["code"] != 0
