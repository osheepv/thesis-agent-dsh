"""NAT-001：研究事实、边界与智能体停止规则契约。"""

from __future__ import annotations

import json

import pytest

from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from common.project_memory import (
    evaluate_revision_stopping,
    project_memory_prompt_block,
    validate_project_memory,
)


def _foundation_payload() -> dict:
    return {
        "research_questions": ["自动草稿如何避免旧请求覆盖新版本？"],
        "scope_boundaries": [
            "当前阶段只支持 DeepSeek 接口",
            "研究事实只能来自批准的证据或用户核验结果投影",
        ],
        "forbidden_claims": ["系统能够替代作者承担学术责任"],
        "unresolved_claims": ["断电瞬间未送达服务端的草稿能否恢复"],
        "stopping_policy": {
            "max_revision_rounds": 3,
            "plateau_rounds": 2,
            "min_score_improvement": 0.5,
        },
        "version_note": "NAT-001 foundation",
    }


def test_foundation_schema_accepts_legacy_and_rejects_duplicate_contract_items():
    legacy = validate_project_memory({
        "research_questions": ["旧客户端仍可创建项目记忆吗？"],
    })
    assert legacy.scope_boundaries == []
    assert legacy.stopping_policy.max_revision_rounds == 3

    duplicate = _foundation_payload()
    duplicate["forbidden_claims"].append(duplicate["forbidden_claims"][0])
    with pytest.raises(ValueError, match="禁写主张不得重复"):
        validate_project_memory(duplicate)
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_project_memory({
            "research_questions": ["不能绕过证据账本吗？"],
            "canonical_facts": ["未经证据核验的自由文本事实"],
        })


def test_foundation_fields_are_versioned_approved_and_prompt_visible():
    orchestration = MainOrchestration()
    task_id = orchestration.create_task(
        "NAT-001 原生学术契约", Degree.MASTER, "软件工程",
        session_id="nat-foundation",
    ).data["task_id"]

    created = orchestration.create_project_memory(task_id, _foundation_payload()).data
    assert created["status"] == "WAITING_APPROVAL"
    assert created["gate_report"]["scope_boundary_count"] == 2
    assert created["gate_report"]["forbidden_claim_count"] == 1
    assert created["gate_report"]["unresolved_claim_count"] == 1
    assert created["gate_report"]["stopping_policy"]["max_revision_rounds"] == 3
    stored = orchestration._artifacts.get(created["artifact_id"])  # noqa: SLF001
    assert stored.context_manifest.prompt_version == "v2"
    orchestration.review_project_memory(task_id, created["artifact_id"], approved=True)
    active = orchestration._active_project_memory(task_id)  # noqa: SLF001

    assert active is not None
    assert active.payload["scope_boundaries"][0].startswith("当前阶段")
    assert active.payload["stopping_policy"]["max_revision_rounds"] == 3
    prompt = project_memory_prompt_block(active.payload, max_chars=10_000)
    assert "研究事实只能来自批准的证据" in prompt
    assert "系统能够替代作者承担学术责任" in prompt
    assert "断电瞬间未送达服务端" in prompt


def test_project_memory_prompt_truncation_remains_valid_json():
    payload = _foundation_payload()
    payload["scope_boundaries"] = [f"边界-{index}-" + ("长文本" * 30) for index in range(20)]
    block = project_memory_prompt_block(payload, max_chars=420)
    serialized = block.split("\n", 1)[1]
    parsed = json.loads(serialized)
    assert len(serialized) <= 420
    assert parsed["_truncated"] is True
    assert all("边界-" in item for item in parsed.get("scope_boundaries", []))


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"target_reached": True}, "TARGET_REACHED"),
        ({"evidence_gaps": ["核心结论缺少批准证据"]}, "EVIDENCE_GAP"),
        ({"specialist_conflicts": ["统计与领域专家结论冲突"]}, "SPECIALIST_CONFLICT"),
        ({"completed_rounds": 3}, "MAX_ROUNDS"),
        ({"score_history": [6.0, 6.2, 6.4]}, "SCORE_PLATEAU"),
    ],
)
def test_revision_stopping_policy_returns_auditable_stop_reason(kwargs, reason):
    decision = evaluate_revision_stopping(_foundation_payload()["stopping_policy"], **kwargs)
    assert decision["should_stop"] is True
    assert decision["reason"] == reason
    assert decision["next_action"]


def test_revision_stopping_policy_allows_meaningful_progress():
    decision = evaluate_revision_stopping(
        _foundation_payload()["stopping_policy"],
        completed_rounds=2,
        score_history=[5.0, 5.8, 6.5],
    )
    assert decision == {
        "should_stop": False,
        "reason": "CONTINUE",
        "next_action": "继续当前有界修订",
    }


def test_hard_evidence_gap_precedes_target_reached():
    decision = evaluate_revision_stopping(
        _foundation_payload()["stopping_policy"],
        target_reached=True,
        evidence_gaps=["核心事实仍无批准证据"],
        specialist_conflicts=["专家意见仍冲突"],
    )
    assert decision["reason"] == "EVIDENCE_GAP"
