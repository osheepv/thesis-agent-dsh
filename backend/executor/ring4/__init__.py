# -*- coding: utf-8 -*-
"""环4 综述评审执行体（HITL 预留，本期仅留接口）。

M2 一期预告：综述评审属于 HITL 通过式网关环节（环2/4/8/10 之一），
需要人工确认文献综述质量，本期只定义骨架。

DSH 二期接入点：接入综述评审 LLM 生成 + 人工确认流程。
"""
from __future__ import annotations

from common.aicoding.enums import RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
)


class Ring4ReviewExecutor(RingExecutor):
    """环4 综述评审执行体（HITL 预留，未实现）。"""

    ring_type: RingType = RingType.RING_4
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        """本期未实现，仅预留接口。

        Raises:
            NotImplementedError: 本期不实现，见 base.get_executor 兜底。
        """
        raise NotImplementedError("环4 综述评审为 HITL 预留环节，本期未实现")
