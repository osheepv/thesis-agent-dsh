# -*- coding: utf-8 -*-
"""环7 万方查重执行体（本期仅留骨架）。

M2 一期预告：万方查重属于自动执行环节（M7，非 HITL），本期不作实现，
由骨架占位；二期接入 wanfang 接口。

DSH 二期接入点：接入万方查重接口（ErrorCode.WANFANG_*）。
"""
from __future__ import annotations

from common.aicoding.enums import RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
)


class Ring7DuplicationCheckExecutor(RingExecutor):
    """环7 万方查重执行体（预留，未实现）。"""

    ring_type: RingType = RingType.RING_7
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        """本期未实现，仅预留接口。"""
        raise NotImplementedError("环7 万方查重为预留环节，本期未实现")
