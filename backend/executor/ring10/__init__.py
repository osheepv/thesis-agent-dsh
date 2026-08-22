# -*- coding: utf-8 -*-
"""环10 终稿交付执行体（HITL 预留，本期仅留接口）。

M2 一期预告：终稿交付属于 HITL 通过式网关环节（环2/4/8/10 之一），
需要人工确认最终成稿并交付，本期只定义骨架。

DSH 二期接入点：接入终稿格式排版 + 人工确认交付流程。
"""
from __future__ import annotations

from common.aicoding.enums import RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
)


class Ring10DeliveryExecutor(RingExecutor):
    """环10 终稿交付执行体（HITL 预留，未实现）。"""

    ring_type: RingType = RingType.RING_10
    hitl_required: bool = True

    def execute(self, ctx: ExecContext) -> ExecResult:
        """本期未实现，仅预留接口。

        Raises:
            NotImplementedError: 本期不实现，见 base.get_executor 兜底。
        """
        raise NotImplementedError("环10 终稿交付为 HITL 预留环节，本期未实现")
