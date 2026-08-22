# -*- coding: utf-8 -*-
"""任务相关 DTO。

覆盖主编排用例（创建论文任务）的入参与产出，与会话绑定隔离预留字段。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from common.aicoding.enums.degree import Degree
from common.aicoding.enums.phase_state import PhaseState


class CreateTaskRequest(BaseModel):
    """创建论文任务请求。"""

    title: str = Field(..., description="论文题目")
    degree: Degree = Field(..., description="学位层次")
    subject_field: str = Field(..., description="学科方向")
    template_id: Optional[str] = Field(default=None, description="论文模板 ID（可选）")
    outline: Optional[str] = Field(default=None, description="外部给定大纲（可选，缺省由环5生成）")
    session_id: str = Field(default="", description="会话 ID（M9 知识库隔离预留）")
    tenant_id: str = Field(default="default", description="租户 ID（多租户预留）")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="扩展元信息")


class CreateTaskResult(BaseModel):
    """创建任务产出。"""

    task_id: str = Field(..., description="任务 ID")
    title: str = Field(..., description="论文题目")
    degree: Degree = Field(..., description="学位层次")
    subject_field: str = Field(..., description="学科方向")
    session_id: str = Field(default="", description="会话 ID")


class PhaseProgressView(BaseModel):
    """单环节进度视图项。"""

    ring: str = Field(..., description="环节标识，如 RING_1")
    ring_no: int = Field(..., description="环节编号，如 1")
    label: str = Field(default="", description="环节中文名")
    state: PhaseState = Field(default=PhaseState.NOT_STARTED, description="环节状态")
    output: Optional[str] = Field(default=None, description="环节产出摘要")
    summary: Optional[str] = Field(default=None, description="环节摘要/备注")


class TaskProgressView(BaseModel):
    """任务进度视图。"""

    task_id: str = Field(..., description="任务 ID")
    title: str = Field(..., description="论文题目")
    current_ring: Optional[int] = Field(default=None, description="当前所处环节编号")
    phases: List[PhaseProgressView] = Field(default_factory=list, description="十环节进度")
    status: Optional[str] = Field(default=None, description="总体状态（进行中/已完成）")
    extra: Optional[Dict[str, Any]] = Field(default=None, description="扩展信息")
