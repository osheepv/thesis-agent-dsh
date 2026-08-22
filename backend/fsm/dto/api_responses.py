# -*- coding: utf-8 -*-
"""FSM API 响应 VO。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fsm.state.models import FsmState


class TaskDetailVO(BaseModel):
    """任务详情（GET /api/v1/tasks/{taskId}）。"""

    task_id: str = Field(..., description="任务 ID")
    title: str = Field(default="", description="论文题目")
    degree: str = Field(..., description="学位等级")
    degree_label: str = Field(default="", description="学位中文标签")
    subject_field: str = Field(default="", description="学科方向")
    template_id: str = Field(default="", description="模板 ID")
    current_ring_no: int = Field(..., description="当前环节号 1~10")
    current_ring: str = Field(..., description="当前环节类型")
    current_ring_label: str = Field(default="", description="当前环节中文名")
    prev_ring_no: Optional[int] = Field(default=None, description="前驱环节号")
    phase_state: str = Field(..., description="当前环节阶段态")
    hitl_confirmed: bool = Field(default=False, description="当前 HITL 环节是否已人工确认")
    hitl_required: bool = Field(default=False, description="当前环节是否 HITL 敏感")
    artifacts: Dict[str, str] = Field(default_factory=dict, description="主产物指针")
    aux_artifacts: Dict[str, List[str]] = Field(default_factory=dict, description="附属产物指针")
    rollback_stack_size: int = Field(default=0, description="回退栈深度")
    is_finished: bool = Field(default=False, description="是否已完结")
    created_at: str = Field(default="", description="创建时间")
    updated_at: str = Field(default="", description="更新时间")

    @classmethod
    def from_state(cls, state: FsmState, route_any: Optional[Dict[str, Any]] = None) -> "TaskDetailVO":
        from common.aicoding.enums import PhaseState

        hitl_required = False
        if route_any is not None:
            hitl_required = bool(route_any.get("hitl_required", False))
        elif state.current_route is not None:
            hitl_required = state.current_route.hitl_required

        return cls(
            task_id=state.task_id,
            title=state.title,
            degree=state.degree.value,
            degree_label=state.degree.label,
            subject_field=state.subject_field,
            template_id=state.template_id,
            current_ring_no=state.current_ring_no,
            current_ring=state.ring.value,
            current_ring_label=state.ring.label,
            prev_ring_no=state.prev_ring_no,
            phase_state=state.phase_state.value,
            hitl_confirmed=state.hitl_confirmed,
            hitl_required=hitl_required,
            artifacts=state.artifacts,
            aux_artifacts=state.aux_artifacts,
            rollback_stack_size=len(state.rollback_stack),
            is_finished=state.is_finished,
            created_at=state.created_at.isoformat() if state.created_at else "",
            updated_at=state.updated_at.isoformat() if state.updated_at else "",
        )


class RouteVO(BaseModel):
    """学位路由参数（GET /api/v1/tasks/{taskId}/route）。"""

    total_rings: int = Field(default=10, description="总环节数")
    routes: List[Dict[str, Any]] = Field(default_factory=list, description="十环节逐环节路由配置")
