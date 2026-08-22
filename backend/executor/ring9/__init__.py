# -*- coding: utf-8 -*-
"""环9 定稿排版执行体（本期仅留骨架）。

M2 一期预告：定稿排版属于自动执行环节（M9 相关，非 HITL），本期不作实现，
由骨架占位；二期接入 docx 模板生成。

DSH 二期接入点：接入 docx 模板解析/生成（ErrorCode.DOCX_*）。
"""
from __future__ import annotations

from common.aicoding.enums import RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
)


class Ring9TypesetExecutor(RingExecutor):
    """环9 定稿排版执行体（预留，未实现）。"""

    ring_type: RingType = RingType.RING_9
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        """本期未实现，仅预留接口。"""
        raise NotImplementedError("环9 定稿排版为预留环节，本期未实现")
