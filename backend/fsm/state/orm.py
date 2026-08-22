# -*- coding: utf-8 -*-
"""M4 状态存储 —— SQLAlchemy 2.0 ORM 模型。

本模块提供落库映射（生产环境），与 fsm/state/models.py 的领域对象相互转换。
对应物理表（骨架约定）：
    t_fsm_state  FSM 运行时状态
    t_task       任务主表（本模块仅提供最小字段，用于 FSM 关联读，DDL 由骨架模块建立）

约束：仅使用 SQLAlchemy 2.0 语法（DeclarativeBase + Mapped），不出现 MySQL 专用语法。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Integer, Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class FSMBase(DeclarativeBase):
    """FSM 模块 ORM 基类。"""


class FsmStateModel(FSMBase):
    """t_fsm_state —— FSM 运行时状态。"""

    __tablename__ = "t_fsm_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(index=True, unique=True, comment="任务 ID")
    # 当前环节号 1~10
    current_ring_no: Mapped[int] = mapped_column(comment="当前环节号")
    # 学位等级
    degree: Mapped[str] = mapped_column(comment="学位等级 BACHELOR/MASTER/PHD")
    # 前驱环节号
    prev_ring_no: Mapped[Optional[int]] = mapped_column(nullable=True, comment="前驱环节号")
    # 回退栈 JSON（数组：[{prev_ring, phase_state, snapshot, created_at}]）
    rollback_stack: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="回退栈 JSON")
    # 当前环节阶段态
    phase_state: Mapped[str] = mapped_column(comment="阶段态 NOT_STARTED/IN_PROGRESS/PASSED/FALLBACK")
    # 辅助信息
    title: Mapped[str] = mapped_column(default="", comment="论文题目")
    subject_field: Mapped[str] = mapped_column(default="", comment="学科方向")
    template_id: Mapped[str] = mapped_column(default="", comment="论文模板 ID")
    hitl_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, comment="HITL 已人工确认")
    artifacts: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="主产物指针")
    aux_artifacts: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="附属产物指针")
    biz_req_no: Mapped[str] = mapped_column(default="", comment="幂等键（推进请求号）")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class AcceptanceGateModel(FSMBase):
    """t_acceptance_gate —— 验收看门记录（与 FSM 状态同事务）。"""

    __tablename__ = "t_acceptance_gate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(index=True, comment="任务 ID")
    ring_no: Mapped[int] = mapped_column(comment="看门环节号")
    accepted: Mapped[bool] = mapped_column(Boolean, comment="是否通过")
    reject_reason: Mapped[Optional[str]] = mapped_column(nullable=True, comment="驳回原因")
    gate_rule: Mapped[str] = mapped_column(default="internal_acceptance", comment="看门规则名")
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="检查时间")


class TaskModel(FSMBase):
    """t_task —— 任务主表（最小字段，DDL 由骨架模块建立，此处仅做读关联）。

    注意：本模块不负责创建/主导 t_task，仅在创建任务时写入 FSM 所需最小字段，
    遵循“主产物同步、附属异步”的事务边界。其余字段交由骨架/任务域模块扩展。
    """

    __tablename__ = "t_task"

    id: Mapped[str] = mapped_column(primary_key=True, comment="任务 ID")
    title: Mapped[str] = mapped_column(default="", comment="论文题目")
    degree: Mapped[str] = mapped_column(comment="学位等级")
    subject_field: Mapped[str] = mapped_column(default="", comment="学科方向")
    template_id: Mapped[str] = mapped_column(default="", comment="模板 ID")
    status: Mapped[str] = mapped_column(default="CREATED", comment="任务状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


#: 展示用字段映射（ORM → 领域对象）
def fsm_state_to_domain(row: FsmStateModel) -> "Any":
    """ORM 行 → 领域 FsmState（供 service/controller 使用）。"""
    from fsm.state.models import FsmState, RollbackEntry
    from common.aicoding.enums import Degree, PhaseState

    stack: list[RollbackEntry] = []
    if row.rollback_stack:
        for item in row.rollback_stack:
            stack.append(RollbackEntry.from_dict(item))

    return FsmState(
        task_id=row.task_id,
        current_ring_no=row.current_ring_no,
        degree=Degree(row.degree),
        prev_ring_no=row.prev_ring_no,
        rollback_stack=stack,
        phase_state=PhaseState(row.phase_state),
        title=row.title or "",
        subject_field=row.subject_field or "",
        template_id=row.template_id or "",
        hitl_confirmed=row.hitl_confirmed or False,
        artifacts=row.artifacts or {},
        aux_artifacts=row.aux_artifacts or {},
        biz_req_no=row.biz_req_no or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
