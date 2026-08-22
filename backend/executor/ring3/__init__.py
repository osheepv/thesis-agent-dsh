# -*- coding: utf-8 -*-
"""环3 文献综述执行体（本期仅留骨架）。

M2 一期预告：文献综述属于自动执行环节（非 HITL），本期不作实现，
由骨架占位；二期接入 DSH 检索 + 综述生成。

DSH 二期接入点：接入文献检索（wanfang 等）与综述生成流程。
"""
from __future__ import annotations

from common.aicoding.enums import RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
)


class Ring3LiteratureReviewExecutor(RingExecutor):
    """环3 文献综述执行体（预留，未实现）。"""

    ring_type: RingType = RingType.RING_3
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        """本期未实现，仅预留接口。"""
        raise NotImplementedError("环3 文献综述为预留环节，本期未实现")
