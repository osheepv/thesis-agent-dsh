"""项目记忆的版本、审批、API和Agent只读消费测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration
from artifacts import ArtifactRegistry, ArtifactStatus
from common.agent_loop import AgentLoopSettings, ModelToolCall, ModelTurn
from common.aicoding.enums import Degree
from common.llm import StructuredOutputError
from common.project_memory import (
    project_memory_prompt_block,
    validate_project_memory,
)
from executor import ExecContext
from executor import ring6_chapter as r6


def _payload(note: str = "v1") -> dict:
    return {
        "research_questions": ["如何降低论文智能体的虚假引用？"],
        "decisions": [{
            "text": "所有参考文献必须先进入批准文献池",
            "rationale": "保证引用可追溯",
            "source": "AUTHOR",
            "active": True,
        }],
        "supervisor_feedback": [{
            "text": "将引用错误率作为验收指标",
            "status": "ACCEPTED",
            "response": "已纳入实验计划",
        }],
        "terminology": [{
            "term": "Agent Loop",
            "preferred_form": "有界智能体微循环",
            "definition": "受轮数和工具权限限制的任务循环",
            "forbidden_aliases": ["无限自主Agent"],
        }],
        "writing_style": {
            "language": "zh-CN",
            "tone": "客观、审慎",
            "person": "避免第一人称",
            "tense": "按研究事实选择",
            "citation_style": "GB/T 7714-2015",
            "constraints": ["不使用未经验证的数据"],
        },
        "version_note": note,
    }


def test_project_memory_schema_rejects_empty_and_duplicates():
    with pytest.raises(ValueError, match="至少需要一类"):
        validate_project_memory({})
    duplicate = _payload()
    duplicate["research_questions"].append(duplicate["research_questions"][0])
    with pytest.raises(ValueError, match="研究问题不得重复"):
        validate_project_memory(duplicate)
    block = project_memory_prompt_block(_payload(), max_chars=5000)
    assert "有界智能体微循环" in block
    assert "GB/T 7714-2015" in block


def test_project_memory_versions_require_approval_and_supersede_old_version():
    orchestration = MainOrchestration(artifact_registry=ArtifactRegistry())
    task_id = orchestration.create_task(
        "项目记忆", Degree.MASTER, "人工智能", session_id="memory-v"
    ).data["task_id"]

    first = orchestration.create_project_memory(task_id, _payload("v1")).data
    assert first["status"] == "WAITING_APPROVAL"
    assert orchestration._active_project_memory(task_id) is None  # noqa: SLF001
    orchestration.review_project_memory(task_id, first["artifact_id"], approved=True)

    second = orchestration.create_project_memory(task_id, _payload("v2")).data
    orchestration.review_project_memory(task_id, second["artifact_id"], approved=True)
    versions = orchestration.list_project_memories(task_id).data
    active = orchestration._active_project_memory(task_id)  # noqa: SLF001

    assert [item["version"] for item in versions] == [1, 2]
    assert orchestration._artifacts.get(first["artifact_id"]).status == ArtifactStatus.SUPERSEDED  # noqa: SLF001
    assert active is not None and active.artifact_id == second["artifact_id"]


def test_project_memory_console_api(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    orchestration = MainOrchestration(artifact_registry=ArtifactRegistry())
    task = orchestration.create_task(
        "项目记忆API", Degree.BACHELOR, "信息管理", session_id="memory-api"
    ).data
    client = TestClient(build_app(orchestration=orchestration))
    base = f"/api/v1/console/tasks/{task['task_id']}/memory?session_id=memory-api"

    created = client.post(base, json=_payload()).json()
    artifact_id = created["data"]["artifact_id"]
    approved = client.post(
        f"/api/v1/console/tasks/{task['task_id']}/memory/{artifact_id}/review?session_id=memory-api",
        json={"approved": True, "actor": "author"},
    ).json()
    listed = client.get(base).json()

    assert created["code"] == 0
    assert approved["data"]["status"] == "APPROVED"
    assert listed["data"][0]["payload"]["version_note"] == "v1"


def test_ring6_agent_must_read_approved_project_memory(monkeypatch):
    turns = iter([
        ModelTurn(tool_calls=(ModelToolCall(
            "memory-read", "read_approved_context", '{"kind":"project_memory"}'
        ),)),
        ModelTurn(content=json.dumps({
            "chapter_plans": [{
                "chapter_no": 1,
                "objectives": ["按项目记忆统一术语"],
                "suggested_refs": [],
                "evidence_gaps": [],
            }],
            "global_notes": ["使用审慎语气"],
        }, ensure_ascii=False)),
    ])
    client = type("Client", (), {
        "complete_with_tools": staticmethod(lambda *_: next(turns)),
    })()
    monkeypatch.setattr(r6, "get_llm_client", lambda: client)
    ctx = ExecContext(
        subject_field="AI",
        degree=Degree.MASTER,
        theme="T",
        outline=json.dumps({"chapters": [
            {"level": 1, "number": "第1章", "title": "绪论"},
        ]}, ensure_ascii=False),
        literature=[],
    )
    ctx.project_memory = _payload()
    ctx.project_memory_artifact_id = "ART-MEMORY"

    plan = r6._build_writing_plan(  # noqa: SLF001
        ctx, "T", [("第1章", "绪论")], AgentLoopSettings(max_turns=3)
    )

    assert plan["agent_context_reads"] == ["project_memory"]
    assert plan["project_memory_artifact_id"] == "ART-MEMORY"


def test_ring6_agent_rejects_skipped_project_memory(monkeypatch):
    turns = iter([
        ModelTurn(tool_calls=(ModelToolCall(
            "outline-read", "read_approved_context", '{"kind":"outline"}'
        ),)),
        ModelTurn(content=json.dumps({
            "chapter_plans": [{
                "chapter_no": 1,
                "objectives": ["目标"],
                "suggested_refs": [],
                "evidence_gaps": [],
            }],
            "global_notes": [],
        }, ensure_ascii=False)),
    ])
    client = type("Client", (), {
        "complete_with_tools": staticmethod(lambda *_: next(turns)),
    })()
    monkeypatch.setattr(r6, "get_llm_client", lambda: client)
    ctx = ExecContext(
        subject_field="AI",
        degree=Degree.MASTER,
        theme="T",
        outline=json.dumps({"chapters": []}),
        literature=[],
    )
    ctx.project_memory = _payload()

    with pytest.raises(StructuredOutputError, match="未读取已批准项目记忆"):
        r6._build_writing_plan(  # noqa: SLF001
            ctx, "T", [("第1章", "绪论")], AgentLoopSettings(max_turns=3)
        )
