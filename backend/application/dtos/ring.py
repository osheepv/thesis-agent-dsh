# -*- coding: utf-8 -*-
"""环节执行结果 DTO。

对齐 M2 执行体各环节统一返回的四字段产出：
    output      环节主产出（候选题目 / 章节结构 / 初稿正文）
    accept      是否通过（True 表示自动通过）
    fallbackTo  需回退到的环节（未通过时，可选）
    issues      问题/告警列表
    evidence    证据列表（供二次校验与追溯）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from common.aicoding.enums.phase_state import PhaseState


class RingExecutionResult(BaseModel):
    """M2 环节执行结果（四字段 + 状态补充）。"""

    output: Optional[Any] = Field(default=None, description="环节主产出")
    accept: bool = Field(default=False, description="是否自动通过")
    fallbackTo: Optional[int] = Field(default=None, description="需回退到的环节编号")
    issues: List[Dict[str, Any]] = Field(default_factory=list, description="问题/告警列表")
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="证据列表")
    state: PhaseState = Field(default=PhaseState.PASSED, description="环节状态")


class Ring1SelectionResult(BaseModel):
    """环1 选题产出。"""

    candidates: List[Dict[str, Any]] = Field(default_factory=list, description="候选题目集合")
    chosen: Optional[str] = Field(default=None, description="已选题目（可为空，交由用户确认）")
    reason: Optional[str] = Field(default=None, description="选题推理说明")


class Ring5OutlineResult(BaseModel):
    """环5 大纲产出。"""

    outline: str = Field(default="", description="大纲正文")
    chapters: List[Dict[str, Any]] = Field(default_factory=list, description="章节结构")
    approach: Optional[str] = Field(default=None, description="研究思路说明")


class Ring6DraftResult(BaseModel):
    """环6 初稿撰写产出。"""

    chapter_no: Optional[int] = Field(default=None, description="本章节号（批量撰写时）")
    content: str = Field(default="", description="初稿正文")
    word_count: int = Field(default=0, description="字数统计")
