# -*- coding: utf-8 -*-
"""公共枚举模块。"""
from .degree import Degree
from .ring_type import RingType, RING_TYPE_DEFAULT_DURATION
from .phase_state import PhaseState
from .guardrail_type import GuardrailType

__all__ = [
    "Degree",
    "RingType",
    "RING_TYPE_DEFAULT_DURATION",
    "PhaseState",
    "GuardrailType",
]
