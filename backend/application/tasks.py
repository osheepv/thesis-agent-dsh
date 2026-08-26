# -*- coding: utf-8 -*-
"""统一任务创建/查询API。

``/api/v1/tasks`` 与写作者控制台共享 ``MainOrchestration``、FSM和持久化
``_TaskStore``，不再维护第二份内存任务表。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from common.aicoding.dto import BaseRequest, PageRequest, PageResponse, Result
from common.aicoding.enums import Degree, RingType
from common.aicoding.exception import BizException, ErrorCode

from .service.uc_main_orchestration import MainOrchestration


router = APIRouter(prefix="/api/v1/tasks", tags=["task"])


class CreateTaskRequest(BaseRequest):
    title: str
    degree: Degree
    discipline: Optional[str] = None
    start_ring: RingType = RingType.RING_1


class TaskSummary(BaseRequest):
    task_id: str
    task_no: str
    title: str
    degree: str
    discipline: Optional[str] = None
    status: str = "NOT_STARTED"
    current_ring: str = "RING_1"
    complete_percent: float = 0.0


def get_orchestration(request: Request) -> MainOrchestration:
    return request.app.state.orchestration


def _summary(data: dict[str, Any], request: BaseRequest | None = None) -> TaskSummary:
    return TaskSummary(
        task_id=str(data.get("task_id", "")),
        task_no=str(data.get("task_no") or data.get("task_id", "")),
        title=str(data.get("title", "")),
        degree=str(data.get("degree", "")),
        discipline=str(data.get("subject_field", "")) or None,
        status=str(data.get("status", "NOT_STARTED")),
        current_ring=str(data.get("current_ring", "RING_1")),
        complete_percent=float(data.get("complete_percent", 0) or 0),
        session_id=str(data.get("session_id", "")),
        tenant_id=str(data.get("tenant_id", "default")),
        trace_id=request.trace_id if request is not None else None,
    )


@router.post("", response_model=Result[TaskSummary])
async def create_task(
    req: CreateTaskRequest,
    request: Request,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[TaskSummary]:
    if req.start_ring != RingType.RING_1:
        raise BizException(ErrorCode.INVALID_PARAM, "论文任务必须从环1开始")
    principal = getattr(request.state, "principal", None)
    tenant_id = principal.tenant_id if principal is not None else req.tenant_id
    owner_user_id = principal.user_id if principal is not None else ""
    created = orchestration.create_task(
        title=req.title,
        degree=req.degree,
        subject_field=req.discipline or "",
        session_id=req.session_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    view = orchestration.get_task_view(str(created.data["task_id"]))
    return Result.ok(
        data=_summary(view.data, req),
        trace_id=req.trace_id,
        tenant_id=tenant_id,
    )


@router.get("", response_model=Result[PageResponse[TaskSummary]])
async def list_tasks(
    request: Request,
    page: PageRequest = Depends(),
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[PageResponse[TaskSummary]]:
    principal = getattr(request.state, "principal", None)
    tenant_id = principal.tenant_id if principal is not None else ""
    values = list(orchestration.list_tasks(tenant_id=tenant_id).data or [])
    if page.keyword:
        keyword = page.keyword.casefold().strip()
        values = [
            item
            for item in values
            if keyword in str(item.get("title", "")).casefold()
            or keyword in str(item.get("degree", "")).casefold()
        ]
    total = len(values)
    start = (page.page - 1) * page.size
    items = [
        _summary(orchestration.get_task_view(str(item["task_id"])).data)
        for item in values[start:start + page.size]
    ]
    return Result.ok(
        data=PageResponse[TaskSummary](
            total=total,
            page=page.page,
            size=page.size,
            items=items,
        ),
        tenant_id=tenant_id or "default",
    )


@router.get("/{task_id}", response_model=Result[TaskSummary])
async def get_task(
    task_id: str,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[TaskSummary]:
    return Result.ok(data=_summary(orchestration.get_task_view(task_id).data))
