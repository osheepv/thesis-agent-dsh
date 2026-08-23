"""论证图校验、论断投影与下游失效传播测试。"""

from __future__ import annotations

import json

import pytest

from artifacts import ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from evidence import ClaimType, EvidenceLedger
from executor.base import ExecResult
from research import ArgumentClaimSpec, ArgumentMap, ArgumentRole
from research import ResearchExecutionRegistry


class _Executor:
    def __init__(self, ring_no: int) -> None:
        self.ring_no = ring_no

    def execute(self, ctx) -> ExecResult:
        payloads = {
            1: {"candidates": [{"title": "可审计论证图"}], "recommendation": "推荐"},
            2: {"novelty_level": "HIGH", "similar_count": 0, "recommendation": "通过"},
            3: {"items": [{"title": "Argument Graph", "doi": "10.1/graph"}], "summary": "1条"},
            4: {"verdict": "顺", "overlap_count": 0, "recommendation": "通过"},
            5: {
                "theme": "可审计论证图",
                "chapters": [
                    {"level": 1, "number": "1", "title": "绪论"},
                    {"level": 2, "number": "1.2", "title": "核心贡献"},
                    {"level": 2, "number": "4.2", "title": "事实验证"},
                    {"level": 2, "number": "5.3", "title": "局限讨论"},
                ],
                "summary": "大纲",
            },
        }
        return ExecResult(
            output=json.dumps(payloads[self.ring_no], ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


def _orchestration(monkeypatch) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Executor(int(ring_no)),
    )
    return MainOrchestration(
        artifact_registry=ArtifactRegistry(),
        evidence_ledger=EvidenceLedger(),
        research_registry=ResearchExecutionRegistry(),
    )


def _advance_to_ring5(orchestration: MainOrchestration) -> str:
    task_id = orchestration.create_task(
        "论证图", Degree.MASTER, "计算机科学", session_id="argument-map"
    ).data["task_id"]
    for ring_no, runner in (
        (1, orchestration.run_ring1),
        (2, orchestration.run_ring2),
        (3, orchestration.run_ring3),
        (4, orchestration.run_ring4),
    ):
        runner(task_id)
        orchestration.confirm_ring(task_id, ring_no)
    return task_id


def _map_payload(suffix: str = "v1") -> dict:
    return {
        "title": f"论文智能体论证图-{suffix}",
        "research_questions": ["证据绑定是否降低引用错误？"],
        "claims": [
            {
                "claim_key": "ROOT",
                "text": f"证据绑定能够降低引用错误-{suffix}",
                "section_id": "1.2",
                "claim_type": "CONTRIBUTION",
                "role": "THESIS",
                "parent_keys": [],
                "evidence_requirements": ["对照实验", "错误案例审计"],
            },
            {
                "claim_key": "C1",
                "text": "逐条来源核验可减少虚假引用",
                "section_id": "4.2",
                "claim_type": "FACTUAL",
                "role": "CLAIM",
                "parent_keys": ["ROOT"],
                "evidence_requirements": ["引用错误率"],
            },
            {
                "claim_key": "C2",
                "text": "人工复核会增加完成时间",
                "section_id": "5.3",
                "claim_type": "INTERPRETIVE",
                "role": "COUNTERCLAIM",
                "parent_keys": ["ROOT"],
                "evidence_requirements": ["任务耗时"],
            },
        ],
    }


def test_argument_map_rejects_cycles():
    with pytest.raises(ValueError, match="循环"):
        ArgumentMap(
            title="cyclic",
            research_questions=("RQ",),
            claims=(
                ArgumentClaimSpec(
                    claim_key="A", text="A", section_id="1.1",
                    claim_type=ClaimType.FACTUAL, role=ArgumentRole.THESIS,
                    parent_keys=("B",),
                ),
                ArgumentClaimSpec(
                    claim_key="B", text="B", section_id="1.2",
                    claim_type=ClaimType.FACTUAL, role=ArgumentRole.CLAIM,
                    parent_keys=("A",),
                ),
            ),
        )


def test_approved_argument_map_projects_claims_idempotently(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    argument_map = orchestration.create_argument_map(task_id, _map_payload()).data

    with pytest.raises(Exception, match="论证图尚未"):
        orchestration.run_ring5(task_id)
    orchestration.review_argument_map(
        task_id, argument_map["artifact_id"], approved=True
    )
    orchestration.review_argument_map(
        task_id, argument_map["artifact_id"], approved=True
    )
    claims = orchestration.list_claims(
        task_id, artifact_id=argument_map["artifact_id"]
    ).data
    assert len(claims) == 3
    assert all(claim["source_key"].startswith(argument_map["artifact_id"]) for claim in claims)

    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    artifacts = orchestration.list_artifacts(task_id).data
    outline = next(item for item in artifacts if item["kind"] == "OUTLINE")
    ring4 = next(item for item in artifacts if item["stage_no"] == 4)
    assert set(outline["dependency_ids"]) == {
        ring4["artifact_id"], argument_map["artifact_id"]
    }


def test_new_argument_map_version_marks_old_outline_stale(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    first = orchestration.create_argument_map(task_id, _map_payload("v1")).data
    orchestration.review_argument_map(task_id, first["artifact_id"], approved=True)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    old_outline = next(
        item for item in orchestration.list_artifacts(task_id).data if item["kind"] == "OUTLINE"
    )

    orchestration._fsm.rollback(task_id, 5)
    second = orchestration.create_argument_map(task_id, _map_payload("v2")).data
    orchestration.review_argument_map(task_id, second["artifact_id"], approved=True)
    artifacts = orchestration.list_artifacts(task_id).data
    old_map = next(item for item in artifacts if item["artifact_id"] == first["artifact_id"])
    stale_outline = next(
        item for item in artifacts if item["artifact_id"] == old_outline["artifact_id"]
    )
    assert old_map["status"] == "SUPERSEDED"
    assert stale_outline["status"] == "STALE"
