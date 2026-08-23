# -*- coding: utf-8 -*-
"""主编排十环闭环端到端测试。

重点验证每一环都严格遵守「执行 → WAITING_APPROVAL → 用户确认 → 下一环」，
并阻止跨环调用。执行体和 docx 在本文件中使用确定性替身，真实能力由各模块
自己的集成测试覆盖。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from common.aicoding.enums import Degree
from application.service.uc_main_orchestration import MainOrchestration
from executor.base import ExecResult


class FakeRingExecutor:
    """返回满足各编排方法契约的最小环产物。"""

    def __init__(self, ring_no: int) -> None:
        self.ring_no = ring_no

    def execute(self, ctx) -> ExecResult:
        payloads = {
            1: {"candidates": [{"title": "可信论文题目"}], "recommendation": "推荐"},
            2: {"novelty_level": "HIGH", "similar_count": 0, "recommendation": "通过"},
            3: {"items": [{"title": "真实文献", "doi": "10.1000/test"}], "summary": "1条"},
            4: {"verdict": "顺", "overlap_count": 0, "recommendation": "通过"},
            5: {"theme": "可信论文题目", "chapters": [{"level": 1, "number": "1", "title": "绪论"}], "summary": "大纲"},
            6: {"chapters": [{"chapter_no": 1, "chapter_title": "绪论", "content": "正文 [L1]", "word_count": 8}], "total_words": 8, "used_refs": ["[L1]"]},
            7: {"chapters": [{"chapter_no": 1, "chapter_title": "绪论", "content": "润色正文 [L1]", "word_count": 10}], "total_words": 10},
            8: {"total": 1, "passed": 1, "uncertain": 0, "failed": 0, "summary": "通过"},
            9: {"issues": [], "summary": "版式通过"},
            10: {"rings": [{"ring_no": i, "status": "通过"} for i in range(1, 10)], "materials_missing": [], "summary": "可交付"},
        }
        return ExecResult(
            output=json.dumps(payloads[self.ring_no], ensure_ascii=False),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence={"source": "test-double"},
        )


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
def orchestration(monkeypatch) -> MainOrchestration:
    """主编排用例（注入 mock docx 渲染端口，FSM/executor 使用真实内存实现）。"""
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: FakeRingExecutor(int(ring_no)),
    )
    return MainOrchestration(docx_renderer=MockDocxRenderer())


RING_RUNNERS = {
    1: "run_ring1", 2: "run_ring2", 3: "run_ring3", 4: "run_ring4", 5: "run_ring5",
    6: "run_ring6", 7: "run_ring7", 8: "run_ring8", 9: "run_ring9", 10: "run_ring10",
}


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

    for ring_no, method_name in RING_RUNNERS.items():
        if ring_no == 9:
            assert orchestration.generate_docx(task_id).is_ok
        result = getattr(orchestration, method_name)(task_id)
        assert result.is_ok, f"环{ring_no}: {result.msg}"
        pending = orchestration.progress(task_id).data
        assert pending["current_ring_no"] == ring_no
        assert pending["phase_state"] == "WAITING_APPROVAL"
        assert pending["can_confirm"] is True
        confirmed = orchestration.confirm_ring(task_id, ring_no)
        assert confirmed.is_ok

    final = orchestration.progress(task_id).data
    assert final["current_ring_no"] == 10
    assert final["phase_state"] == "PASSED"
    assert final["complete_percent"] == 100.0
    assert all(r["state"] == "PASSED" for r in final["rings"])


def test_docx_requires_ring9_and_uses_polished_draft(orchestration: MainOrchestration, monkeypatch):
    """docx 不得提前生成，进入环9后应使用环7润色稿。"""
    created = orchestration.create_task("文档时序", Degree.MASTER, "NLP", session_id="docx-flow")
    tid = created.data["task_id"]
    with pytest.raises(Exception):
        orchestration.generate_docx(tid)

    captured = {}
    original_generate = orchestration._docx.generate

    def capture_generate(template_id, content, **meta):
        captured.update(content)
        return original_generate(template_id, content, **meta)

    monkeypatch.setattr(orchestration._docx, "generate", capture_generate)
    for ring_no in range(1, 9):
        result = getattr(orchestration, RING_RUNNERS[ring_no])(tid)
        assert result.is_ok
        orchestration.confirm_ring(tid, ring_no)

    generated = orchestration.generate_docx(tid)
    assert generated.is_ok
    assert "润色正文" in captured["content"]


def test_progress_advances_per_step(orchestration: MainOrchestration):
    """验证 FSM 状态随环节推进逐步演进。"""
    r = orchestration.create_task("测试进度", Degree.BACHELOR, "数据挖掘", session_id="sess-2")
    tid = r.data["task_id"]
    assert orchestration.progress(tid).data["current_ring_no"] == 1
    orchestration.run_ring1(tid)
    pending = orchestration.progress(tid).data
    assert pending["current_ring_no"] == 1
    assert pending["phase_state"] == "WAITING_APPROVAL"
    orchestration.confirm_ring(tid, 1)
    assert orchestration.progress(tid).data["current_ring_no"] == 2
    with pytest.raises(Exception):
        orchestration.run_ring5(tid)


def test_session_guard_rejects_foreign_session(orchestration: MainOrchestration):
    """会话隔离：非归属会话不能访问任务。"""
    r = orchestration.create_task("会话隔离", Degree.MASTER, "NLP", session_id="sess-a")
    tid = r.data["task_id"]
    # 显式传入的唯一会话可访问
    orchestration.assert_session(tid, "sess-a")
    # 非归属会话应拒绝
    from common.aicoding.exception import BizException, ErrorCode

    with pytest.raises(BizException) as exc:
        orchestration.assert_session(tid, "sess-b")
    assert exc.value.code == ErrorCode.FORBIDDEN.value


def test_default_session_is_unique_per_task(orchestration: MainOrchestration):
    """空/default 会话不得让多个论文任务共享知识库。"""
    first = orchestration.create_task("任务一", Degree.MASTER, "NLP", session_id="default")
    second = orchestration.create_task("任务二", Degree.MASTER, "NLP", session_id="default")
    assert first.data["session_id"] == first.data["task_id"]
    assert second.data["session_id"] == second.data["task_id"]
    assert first.data["session_id"] != second.data["session_id"]


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
def client(monkeypatch) -> TestClient:
    from application.main import build_app

    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: FakeRingExecutor(int(ring_no)),
    )
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

    paths = {
        1: "/rings/1/execute", 2: "/rings/2/review", 3: "/rings/3/execute",
        4: "/rings/4/review", 5: "/rings/5/outline", 6: "/rings/6/chapter",
        7: "/rings/7/polish", 8: "/rings/8/validate", 9: "/rings/9/layout",
        10: "/rings/10/final",
    }
    for ring_no, path in paths.items():
        if ring_no == 9:
            docx = client.post(f"/api/v1/console/tasks/{tid}/docx/generate?session_id=sess-http")
            assert docx.json()["code"] == 0
        rr = client.post(f"/api/v1/console/tasks/{tid}{path}?session_id=sess-http")
        assert rr.status_code == 200
        assert rr.json()["code"] == 0, f"{path}: {rr.text}"
        pending = client.get(f"/api/v1/console/tasks/{tid}/progress?session_id=sess-http").json()["data"]
        assert pending["current_ring_no"] == ring_no
        assert pending["phase_state"] == "WAITING_APPROVAL"
        confirm = client.post(
            f"/api/v1/console/tasks/{tid}/rings/{ring_no}/confirm?session_id=sess-http",
            json={"confirmed": True},
        )
        assert confirm.json()["code"] == 0, confirm.text

    # 进度
    rp = client.get(f"/api/v1/console/tasks/{tid}/progress?session_id=sess-http")
    assert rp.status_code == 200
    data = rp.json()["data"]
    assert data["current_ring_no"] == 10
    assert data["phase_state"] == "PASSED"
    assert data["complete_percent"] == 100.0


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
