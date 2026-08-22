# -*- coding: utf-8 -*-
"""FSM API 请求/响应 DTO。

请求 DTO：
    - CreateTaskRequest    创建论文任务
    - AdvanceRequest       推进当前环节（bizReqNo 幂等键）
    - RollbackRequest      回退到目标环节
    - ConfirmHitlRequest   HITL 人工确认（M3 网关预留）

响应 VO（TaskDetailVO / RouteVO / ProgressVO）由 orchestrator 返回 dict 组装，
本处提供响应包装类型以复用 Result[T] 信封。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from common.aicoding.dto import BaseRequest


class CreateTaskRequest(BaseRequest):
    """创建论文任务。"""

    title: str = Field(..., min_length=1, max_length=200, description="论文题目")
    degree: str = Field(..., description="学位等级 BACHELOR/MASTER/PHD")
    subject_field: str = Field(default="", description="学科方向")
    template_id: str = Field(default="", description="论文模板 ID")


class AdvanceRequest(BaseRequest):
    """推进当前环节（幂等键 bizReqNo）。"""

    biz_req_no: str = Field(..., min_length=1, max_length=64, description="幂等请求号")
    accept: bool = Field(default=True, description="验收是否通过，默认通过")
    reject_reason: Optional[str] = Field(default=None, description="驳回原因（accept=False 时必填）")
    artifact_uri: Optional[str] = Field(default=None, description="主产物 URI（同步产物）")
    gate_rule: str = Field(default="internal_acceptance", description="验收看门规则名")


class RollbackRequest(BaseRequest):
    """回退到目标环节。"""

    target_ring_no: int = Field(..., ge=1, le=10, description="目标环节号 1~10")


class ConfirmHitlRequest(BaseRequest):
    """HITL 人工确认（M3 网关预留，本轮仅落状态）。"""

    confirmed: bool = Field(default=True, description="是否人工确认通过")
    reject_reason: Optional[str] = Field(default=None, description="驳回原因（confirmed=False 时必填）")
