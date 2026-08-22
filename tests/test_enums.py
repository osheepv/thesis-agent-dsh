# -*- coding: utf-8 -*-
"""枚举单元测试：Degree / RingType / PhaseState / GuardrailType。"""
from __future__ import annotations

from common.aicoding.enums import Degree, GuardrailType, PhaseState, RingType, RING_TYPE_DEFAULT_DURATION


def test_degree_values_and_label():
    assert Degree.BACHELOR.value == "BACHELOR"
    assert Degree.MASTER.value == "MASTER"
    assert Degree.PHD.value == "PHD"
    assert Degree.BACHELOR.label == "本科"
    assert Degree.MASTER.label == "硕士"
    assert Degree.PHD.label == "博士"


def test_degree_min_word_requirement():
    assert Degree.BACHELOR.min_word_requirement == 10000
    assert Degree.MASTER.min_word_requirement == 30000
    assert Degree.PHD.min_word_requirement == 60000


def test_degree_must_cover_all_three_levels():
    assert len(list(Degree)) == 3


def test_ring_type_has_ten_rings():
    assert len(list(RingType)) == 10
    assert RingType.RING_1.value == "RING_1"
    assert RingType.RING_10.value == "RING_10"


def test_ring_type_label():
    assert RingType.RING_1.label == "选题"
    assert RingType.RING_5.label == "大纲生成"
    assert RingType.RING_6.label == "初稿撰写"


def test_ring_type_hitl_gate():
    assert RingType.RING_2.is_hitl_gate is True
    assert RingType.RING_4.is_hitl_gate is True
    assert RingType.RING_8.is_hitl_gate is True
    assert RingType.RING_10.is_hitl_gate is True
    # 非 HITL 环节
    assert RingType.RING_1.is_hitl_gate is False
    assert RingType.RING_5.is_hitl_gate is False
    assert RingType.RING_6.is_hitl_gate is False


def test_ring_type_default_duration_covers_all():
    assert len(RING_TYPE_DEFAULT_DURATION) == 10
    for ring in RingType:
        assert ring in RING_TYPE_DEFAULT_DURATION, f"缺少 {ring} 的超时基线"


def test_phase_state():
    assert PhaseState.NOT_STARTED.value == "NOT_STARTED"
    assert PhaseState.IN_PROGRESS.value == "IN_PROGRESS"
    assert PhaseState.PASSED.value == "PASSED"
    assert PhaseState.FALLBACK.value == "FALLBACK"


def test_guardrail_type():
    assert GuardrailType.POLICY.value == "POLICY"
    assert GuardrailType.PLAGIARISM.value == "PLAGIARISM"
    assert GuardrailType.FACTUAL.value == "FACTUAL"
