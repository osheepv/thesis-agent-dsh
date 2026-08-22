# -*- coding: utf-8 -*-
"""任务创建/查询路由（一期骨架）。

说明：本期不作真库写入（避免依赖 PostgreSQL 实例），
任务创建以 `Result.ok` 返回内存态 DTO；交叉衔接到 M4 状态存储时替换为真实持久化。
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends

from common.aicoding.dto import BaseRequest, PageResponse, PageRequest, Result
from common.aicoding.enums import Degree, RingType
from common.aicoding.exception import BizException, ErrorCode

router = APIRouter(prefix="/api/v1/tasks", tags=["task"])


class CreateTaskRequest(BaseRequest):
    """创建论文任务请求。"""

    title: str
    degree: Degree
    discipline: Optional[str] = None
    
    # 一期闭环基于 ring1(选题)→ring5(大纲)→ring6(初稿)，可指定起点
    start_ring: RingType = RingType.RING_1


class TaskSummary(BaseRequest):
    """任务概要（DTO 快照，memory 版）。"""

    task_id: str
    task_no: str
    title: str
    degree: str
    discipline: Optional[str] = None
    status: str = "NOT_STARTED"
    current_ring: str = "RING_1"


# 内存态任务表（一期骨架；二期替换为 t_task 持久化）
_IN_MEMORY_TASKS: dict[str, TaskSummary] = {}


@router.post("", response_model=Result[TaskSummary])
async def create_task(req: CreateTaskRequest) -> Result[TaskSummary]:
    """创建论文任务（骨架，返回内存态 summary）。"""
    task_id = uuid.uuid4().hex
    task_no = f"TH{task_id[:8].upper()}"
    summary = TaskSummary(
        task_id=task_id,
        task_no=task_no,
        title=req.title,
        degree=req.degree.value,
        discipline=req.discipline,
        status="NOT_STARTED",
        current_ring=req.start_ring.value,
        session_id=req.session_id,
        tenant_id=req.tenant_id,
        trace_id=req.trace_id,
    )
    _IN_MEMORY_TASKS[task_id] = summary
    return Result.ok(data=summary, trace_id=req.trace_id, tenant_id=req.tenant_id)


@router.get("", response_model=Result[PageResponse[TaskSummary]])
async def list_tasks(page: PageRequest = Depends()) -> Result[PageResponse[TaskSummary]]:
    """分页查询任务（内存态骨架）。"""
    values = list(_IN_MEMORY_TASKS.values())
    total = len(values)
    start = (page.page - 1) * page.size
    items = values[start:start + page.size]
    return Result.ok(data=PageResponse[TaskSummary](total=total, page=page.page, size=page.size, items=items))


@router.get("/{task_id}", response_model=Result[TaskSummary])
async def get_task(task_id: str) -> Result[TaskSummary]:
    """查询单个任务。"""
    task = _IN_MEMORY_TASKS.get(task_id)
    if not task:
        raise BizException(ErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}")
    return Result.ok(data=task)
