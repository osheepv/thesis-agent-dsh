"""研究手册、实验运行和结果血缘模型测试。"""

from __future__ import annotations

import pytest

from research import (
    ExperimentRun,
    ExperimentStatus,
    ResearchMethod,
    ResearchProtocol,
    ResultRecord,
)


def test_research_protocol_requires_execution_and_analysis_plan():
    with pytest.raises(ValueError, match="procedure_steps"):
        ResearchProtocol(
            title="RAG写作质量研究",
            method=ResearchMethod.QUANTITATIVE,
            research_questions=("证据绑定能否减少伪引？",),
            procedure_steps=(),
            analysis_plan=("比较两组伪引率",),
            required_outputs=("实验结果表",),
        )


def test_completed_experiment_requires_user_attestation_and_evidence_files():
    with pytest.raises(ValueError, match="用户确认"):
        ExperimentRun(
            run_id="RUN-1",
            protocol_artifact_id="ART-PROTOCOL",
            status=ExperimentStatus.COMPLETED,
            raw_data_file_ids=("FILE-RAW",),
            user_attested=False,
        )
    with pytest.raises(ValueError, match="原始数据或运行日志"):
        ExperimentRun(
            run_id="RUN-1",
            protocol_artifact_id="ART-PROTOCOL",
            status=ExperimentStatus.COMPLETED,
            user_attested=True,
        )


def test_result_record_keeps_reproduction_lineage():
    result = ResultRecord(
        result_id="RES-1",
        run_id="RUN-1",
        metric="citation_error_rate",
        value="0.031",
        unit="ratio",
        source_file_id="FILE-RAW",
        computation="python analysis.py --metric citation_error_rate",
        table_or_figure_id="TABLE-4-2",
        verified_by_user=True,
    )
    payload = result.to_dict()
    assert payload["source_file_id"] == "FILE-RAW"
    assert payload["computation"].startswith("python analysis.py")
