# -*- coding: utf-8 -*-
"""环节执行状态枚举。"""
from __future__ import annotations

from enum import Enum


class PhaseState(str, Enum):
    """FSM 单环节状态。

    - NOT_STARTED  未开始
    - IN_PROGRESS  执行中
    - WAITING_APPROVAL 已生成产物，等待用户确认
    - PASSED       已由用户确认通过
    - FALLBACK     已回退/降级（遇人工拒绝或重试上限触发）
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PASSED = "PASSED"
    FALLBACK = "FALLBACK"
