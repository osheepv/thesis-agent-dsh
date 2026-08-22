# -*- coding: utf-8 -*-
"""环节执行状态枚举。"""
from __future__ import annotations

from enum import Enum


class PhaseState(str, Enum):
    """FSM 单环节状态。

    - NOT_STARTED  未开始
    - IN_PROGRESS  执行中
    - PASSED       已通过（含自动通过与 HITL 通过）
    - FALLBACK     已回退/降级（遇人工拒绝或重试上限触发）
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FALLBACK = "FALLBACK"
