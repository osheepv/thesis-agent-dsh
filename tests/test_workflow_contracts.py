"""十阶段单一契约源测试。"""

from __future__ import annotations

from common.aicoding.enums import RingType
from common.workflow_contracts import STAGE_CONTRACTS, get_stage_contract, workflow_gap_report


def test_stage_contracts_cover_exactly_ten_rings():
    assert tuple(STAGE_CONTRACTS) == tuple(range(1, 11))
    assert [RingType(f"RING_{i}").label for i in range(1, 11)] == [
        STAGE_CONTRACTS[i].label for i in range(1, 11)
    ]


def test_runtime_labels_match_actual_executors():
    assert get_stage_contract(3).label == "文献调研"
    assert get_stage_contract(7).label == "修改润色"
    assert get_stage_contract(8).label == "引用校验"


def test_research_and_experiment_gaps_are_explicit():
    gaps = workflow_gap_report()
    assert 5 not in gaps
    assert 6 not in gaps
