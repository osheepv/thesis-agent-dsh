"""研究协议、实验状态机、结果血缘和环6门禁测试。"""

from __future__ import annotations

import json

import pytest

from artifacts import ArtifactRegistry
from application.service.uc_main_orchestration import MainOrchestration
from common.aicoding.enums import Degree
from evidence import EvidenceLedger
from executor.base import ExecResult
from research import (
    ExperimentStatus,
    ResearchExecutionRegistry,
    ResearchRegistryError,
)
from writing.generator import SectionGeneration


def test_experiment_registry_enforces_state_and_file_lineage():
    registry = ResearchExecutionRegistry()
    run = registry.create_run(
        task_id="task-1", protocol_artifact_id="ART-PROTOCOL", notes="first run"
    )
    with pytest.raises(ResearchRegistryError, match="不能从"):
        registry.update_run(
            task_id="task-1", run_id=run.run_id, status=ExperimentStatus.COMPLETED,
            raw_data_file_ids=["FILE-RAW"], user_attested=True,
        )

    registry.update_run(
        task_id="task-1", run_id=run.run_id, status=ExperimentStatus.MATERIALS_READY,
        material_file_ids=["FILE-MATERIAL"],
    )
    registry.update_run(
        task_id="task-1", run_id=run.run_id, status=ExperimentStatus.RUNNING,
        code_file_ids=["FILE-CODE"],
    )
    completed = registry.update_run(
        task_id="task-1", run_id=run.run_id, status=ExperimentStatus.COMPLETED,
        raw_data_file_ids=["FILE-RAW"], log_file_ids=["FILE-LOG"], user_attested=True,
    )
    assert completed.user_attested is True

    with pytest.raises(ResearchRegistryError, match="未登记"):
        registry.add_result(
            task_id="task-1", run_id=run.run_id, metric="accuracy", value="0.9",
            source_file_id="FILE-OTHER", computation="python analyze.py",
        )
    result = registry.add_result(
        task_id="task-1", run_id=run.run_id, metric="accuracy", value="0.9",
        source_file_id="FILE-RAW", computation="python analyze.py", unit="ratio",
    )
    assert result.verified_by_user is False
    verified = registry.review_result("task-1", result.result_id, verified_by_user=True)
    assert verified.verified_by_user is True


def test_research_registry_enforces_task_isolation():
    registry = ResearchExecutionRegistry()
    run = registry.create_run(task_id="task-a", protocol_artifact_id="ART-A")
    with pytest.raises(ResearchRegistryError, match="当前任务"):
        registry.get_run("task-b", run.run_id)


class _ResearchFlowExecutor:
    def __init__(self, ring_no: int) -> None:
        self.ring_no = ring_no

    def execute(self, ctx) -> ExecResult:
        if self.ring_no == 7:
            draft = json.loads(ctx.draft)
            total_words = sum(len(item.get("content", "")) for item in draft.get("chapters", []))
            return ExecResult(
                output=json.dumps(
                    {"chapters": draft.get("chapters", []), "total_words": total_words},
                    ensure_ascii=False,
                ),
                accept=True,
                evidence={"source": "test-double"},
            )
        if self.ring_no == 6:
            result_markers = []
            result_ids = []
            for result in list(getattr(ctx, "results", []) or []):
                result_id = result["result_id"]
                target = result.get("table_or_figure_id") or result_id
                result_ids.append(result_id)
                result_markers.append(
                    f"[[BOOKMARK:{target}|结果表]] {result['metric']}={result['value']} [{result_id}]"
                )
            content = "准确率实验分析 [L1]。" + " ".join(result_markers) + ("可信实验正文" * 5000)
            return ExecResult(
                output=json.dumps({
                    "chapters": [{
                        "chapter_no": 1,
                        "chapter_title": "实验结果",
                        "content": content,
                        "word_count": len(content),
                    }],
                    "total_words": len(content),
                    "used_refs": ["[L1]"],
                    "used_result_ids": result_ids,
                }, ensure_ascii=False),
                accept=True,
                evidence={"source": "test-double"},
            )
        payloads = {
            1: {"candidates": [{"title": "可复算论文智能体"}], "recommendation": "推荐"},
            2: {"novelty_level": "HIGH", "similar_count": 0, "recommendation": "通过"},
            3: {
                "items": [
                    {
                        "title": "Research Lineage",
                        "doi": "10.1000/lineage",
                        "reliability": "matched",
                    }
                ],
                "summary": "1条",
            },
            4: {"verdict": "顺", "overlap_count": 0, "recommendation": "通过"},
            5: {
                "theme": "可复算论文智能体",
                "chapters": [{"level": 1, "number": "1", "title": "绪论"}],
                "summary": "大纲",
            },
        }
        return ExecResult(
            output=json.dumps(payloads[self.ring_no], ensure_ascii=False),
            accept=True,
            evidence={"source": "test-double"},
        )


class _ResearchSectionGenerator:
    def generate(self, context) -> SectionGeneration:
        results = context.get("results", [])
        parts = []
        for result in results:
            result_id = result["result_id"]
            target = result.get("table_or_figure_id") or result_id
            parts.append(
                f"[[BOOKMARK:{target}|结果表]] {result['metric']}={result['value']} [{result_id}]"
            )
        target_words = int(context.get("target_word_count", 300))
        content = " ".join(parts) + " [L1] " + ("可信实验分节正文" * ((target_words // 8) + 2))
        return SectionGeneration(
            title=context.get("title", ""),
            content=content,
            covered_claim_ids=[],
            used_evidence_ids=[],
            used_result_ids=[result["result_id"] for result in results],
            generation_source="test-double",
        )


def _orchestration(monkeypatch) -> MainOrchestration:
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _ResearchFlowExecutor(int(ring_no)),
    )
    class _KnowledgeStore:
        def list_documents(self, session_id):
            return [
                {"file_id": file_id, "metadata": {"kind": "other"}}
                for file_id in (
                    "FILE-TASKS", "FILE-CODE", "FILE-RAW", "FILE-LOG",
                    "FILE-MATERIAL", "FILE-OTHER",
                )
            ]

    return MainOrchestration(
        artifact_registry=ArtifactRegistry(),
        evidence_ledger=EvidenceLedger(),
        research_registry=ResearchExecutionRegistry(),
        knowledge_store=_KnowledgeStore(),
        section_generator=_ResearchSectionGenerator(),
    )


def _advance_to_ring5(orchestration: MainOrchestration) -> str:
    task_id = orchestration.create_task(
        "实验工作流", Degree.MASTER, "计算机科学", session_id="research-flow"
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


def _protocol_payload() -> dict:
    return {
        "title": "两组智能体引用错误率对照实验",
        "method": "QUANTITATIVE",
        "research_questions": ["证据绑定能否降低引用错误率？"],
        "hypotheses": ["证据绑定组的错误率更低"],
        "variables": {"independent": "是否启用证据绑定", "dependent": "引用错误率"},
        "procedure_steps": ["准备同一组写作任务", "分别运行两组智能体"],
        "analysis_plan": ["计算两组错误率并进行差异检验"],
        "required_outputs": ["原始输出", "分析脚本", "结果表"],
        "materials": ["任务集", "模型配置"],
        "ethics_requirements": ["不得伪造运行结果"],
    }


def test_empirical_protocol_and_result_ledger_gate_ring6(monkeypatch):
    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    orchestration.run_ring5(task_id)
    protocol = orchestration.create_research_protocol(task_id, _protocol_payload()).data
    assert protocol["status"] == "WAITING_APPROVAL"

    with pytest.raises(Exception, match="研究协议尚未"):
        orchestration.confirm_ring(task_id, 5)
    orchestration.review_research_protocol(
        task_id, protocol["artifact_id"], approved=True
    )
    orchestration.confirm_ring(task_id, 5)

    with pytest.raises(Exception, match="结果账本"):
        orchestration.run_ring6(task_id)
    run = orchestration.create_experiment_run(task_id, {"notes": "controlled run"}).data
    with pytest.raises(Exception, match="不属于当前任务知识库"):
        orchestration.update_experiment_run(
            task_id, run["run_id"],
            {"status": "MATERIALS_READY", "material_file_ids": ["FILE-MISSING"]},
        )
    orchestration.update_experiment_run(
        task_id, run["run_id"],
        {"status": "MATERIALS_READY", "material_file_ids": ["FILE-TASKS"]},
    )
    orchestration.update_experiment_run(
        task_id, run["run_id"],
        {"status": "RUNNING", "code_file_ids": ["FILE-CODE"]},
    )
    orchestration.update_experiment_run(
        task_id, run["run_id"],
        {
            "status": "COMPLETED",
            "raw_data_file_ids": ["FILE-RAW"],
            "log_file_ids": ["FILE-LOG"],
            "user_attested": True,
        },
    )
    result = orchestration.add_result_record(
        task_id,
        run["run_id"],
        {
            "metric": "citation_error_rate",
            "value": "0.10",
            "unit": "ratio",
            "source_file_id": "FILE-RAW",
            "computation": "python analyze.py --metric citation_error_rate",
            "table_or_figure_id": "TABLE-4-1",
        },
    ).data
    assert orchestration.audit_research(task_id).data["can_write_results"] is False
    orchestration.review_result_record(
        task_id, result["result_id"], verified_by_user=True
    )

    result_ledger = orchestration.create_result_ledger(task_id).data
    assert result_ledger["kind"] == "RESULT_LEDGER"
    with pytest.raises(Exception, match="结果账本"):
        orchestration.run_ring6(task_id)
    orchestration.review_result_ledger(
        task_id, result_ledger["artifact_id"], approved=True
    )
    section = orchestration.generate_section_draft(
        task_id, {"section_id": "1", "result_ids": [result["result_id"]]}
    ).data
    assert "[[BOOKMARK:TABLE-4-1|" in section["content"]
    assert f"[{result['result_id']}]" in section["content"]
    orchestration.review_section_draft(
        task_id, section["section_draft_id"], approved=True
    )
    assert orchestration.assemble_section_drafts(task_id).is_ok
    orchestration.confirm_ring(task_id, 6)

    artifacts = orchestration.list_artifacts(task_id).data
    outline = next(item for item in artifacts if item["kind"] == "OUTLINE")
    ledger = next(item for item in artifacts if item["kind"] == "RESULT_LEDGER")
    draft = next(item for item in artifacts if item["kind"] == "SECTION_DRAFT")
    assert set(draft["dependency_ids"]) == {outline["artifact_id"], ledger["artifact_id"]}

    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    citation = orchestration.run_ring8(task_id)
    assert citation.is_ok
    assert citation.data["cross_reference_map"][result["result_id"]] == {
        "target": "TABLE-4-1",
        "display": "表4-1",
    }
    rendered = orchestration._store.get(task_id).ring8["rendered_content"]
    assert "[[BOOKMARK:TABLE-4-1|" in rendered
    assert "[[REF:TABLE-4-1|表4-1]]" in rendered


def test_research_endpoints_are_available(monkeypatch):
    from application.main import build_app
    from fastapi.testclient import TestClient

    orchestration = _orchestration(monkeypatch)
    task_id = _advance_to_ring5(orchestration)
    app = build_app(orchestration=orchestration)
    client = TestClient(app)
    query = "?session_id=research-flow"
    response = client.post(
        f"/api/v1/console/tasks/{task_id}/research/protocols{query}",
        json=_protocol_payload(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["kind"] == "RESEARCH_PROTOCOL"
    listed = client.get(
        f"/api/v1/console/tasks/{task_id}/research/protocols{query}"
    ).json()
    assert len(listed["data"]) == 1
