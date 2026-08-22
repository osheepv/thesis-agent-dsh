# -*- coding: utf-8 -*-
"""Guardrail 类型枚举（M8，二期实现，本期仅定义类型）。"""
from __future__ import annotations

from enum import Enum


class GuardrailType(str, Enum):
    """M8 Guardrail 检查维度（二期实现）。"""

    POLICY = "POLICY"            # 政策红线校验
    FACTUAL = "FACTUAL"          # 事实性校验
    PLAGIARISM = "PLAGIARISM"    # 抄袭/查重命中校验
    FORMAT = "FORMAT"            # 格式合规校验
    STYLE = "STYLE"              # 风格/语言质量校验
    CITATION = "CITATION"        # 引用规范校验
