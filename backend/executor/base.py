# -*- coding: utf-8 -*-
"""M2 环节执行体基础层。

统一约定（对齐系统设计 §3.2.M2）：
- 每个环节执行体封装为 :class:`RingExecutor` 子类，被 M1 FSM 推进时调用。
- 执行体 :meth:`RingExecutor.execute` 返回 :class:`ExecResult`（四（五）字段输出）：
    output    本环节主要内容产物（字符串/Markdown）
    accept    是否通过验收（供 M1 看门，True 通过）
    fallbackTo 若需回退，目标环节号（int，如 5 表示回到大纲；None 表示无需回退）
    issues    发现的问题列表
    evidence  证据/来源（如引用来源）

DSH 二期接入点：本模块与各执行体仅依赖下发的 :class:`ExecContext`，
真实 DSH（LLM/检索）调用作为二期扩展点在注释中标注，本期使用确定性 Mock 生成器保证闭环可运行。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, PhaseState, RingType


class ExecResult(BaseModel):
    """环节执行体统一四（五）字段输出。

    Attributes:
        output: 本环节主要内容产物（命题/大纲/章节草稿正文，Markdown 文本）。
        accept: 是否通过验收（供 M1 看门使用）。
        fallbackTo: 若需回退，目标环节号（如 5 表示回到大纲）；None 表示无需回退。
        issues: 发现的问题列表（供 guardrail / HITL 参考）。
        evidence: 证据/来源映射（如引用来源、数据口径、规则命中说明）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: str = Field(default="", description="本环节主要内容产物")
    accept: bool = Field(default=True, description="是否通过验收")
    fallbackTo: Optional[int] = Field(default=None, description="若需回退，目标环节号")
    issues: list[str] = Field(default_factory=list, description="发现的问题")
    evidence: dict[str, Any] = Field(default_factory=dict, description="证据/来源")


class ExecContext(BaseModel):
    """执行体统一上下文入参。

    由 M1 编排器在做环节推进时组装下发，本文（本期）至少契约上承载：
        subject_field: 学科/专业方向。
        degree: 学位层次（BACHELOR/MASTER/PHD）。
        theme: 已选（或候选）题目，供环5大纲/环6章节引用。
        outline: 环5产出的大纲提要，供环6章节生成引用。
        trace_id / session_id / tenant_id: 数据血缘与会话/租户隔离。
    实际 M2 一期用确定性 Mock，仅需 subject_field + degree 即可闭环。
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    subject_field: str = Field(default="", description="学科/专业方向")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    theme: str = Field(default="", description="题目（环1/5 输出，环6 引用）")
    outline: str = Field(default="", description="大纲提要（环5 输出，环6 引用）")
    trace_id: Optional[str] = Field(default=None, description="追踪 ID")
    session_id: str = Field(default="", description="会话 ID（M9 隔离预留）")
    tenant_id: str = Field(default="default", description="租户 ID")


class RingExecutor(ABC):
    """环节执行体抽象基类。

    每个环节（环1~10）应继承并实现 :meth:`execute`。
    ``ring_type`` 标识所属环节；``hitl_required`` 标识是否为 HITL 通过式网关环节
    （环2/4/8/10 为 True，此类环节本期只留接口不实现）。
    """

    ring_type: RingType = RingType.RING_1
    hitl_required: bool = False
    phase_state: PhaseState = PhaseState.NOT_STARTED

    @abstractmethod
    def execute(self, ctx: ExecContext) -> ExecResult:
        """执行本环节，返回统一输出。"""
        raise NotImplementedError

    def validate_input(self, ctx: ExecContext) -> None:
        """输入校验钩子（子类可覆写）。本期默认只校验 degree 值，可扩展。"""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<{self.__class__.__name__} ring={self.ring_type.value} hitl={self.hitl_required}>"


#: 环节执行体注册表：RingType -> RingExecutor 子类。
EXECUTOR_REGISTRY: dict[RingType, type[RingExecutor]] = {}


def register_executor(runner_cls: type[RingExecutor]) -> type[RingExecutor]:
    """将执行体类注册到 :data:`EXECUTOR_REGISTRY`（装饰器）。"""
    EXECUTOR_REGISTRY[runner_cls.ring_type] = runner_cls
    return runner_cls


def get_executor(ring: RingType | int) -> RingExecutor:
    """按环节号/类型取执行体实例。

    Args:
        ring: RingType 或环节编号（1~10）。

    Raises:
        KeyError: 该环节未注册实现（含 HITL 预留环节本期未实现）。
    """
    ring_type = RingType.RING_1 if isinstance(ring, int) else ring
    if isinstance(ring, int):
        ring_type = RingType(f"RING_{ring}")
    runner_cls = EXECUTOR_REGISTRY.get(ring_type)
    if runner_cls is None:
        raise KeyError(
            f"环节 {ring_type.value} 未注册执行体（HITL 预留环节 2/4/8/10 本期仅留接口）"
        )
    return runner_cls()
