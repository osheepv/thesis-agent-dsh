# -*- coding: utf-8 -*-
"""基础请求对象。

所有 API 请求 DTO 的顶层基类：
- 统一携带 session_id（会话绑定知识库隔离，M9 预留）与 tenant_id（多租户预留）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class BaseRequest(BaseModel):
    """API 请求基类。

    Attributes:
        session_id: 会话 ID。用于 M9 会话绑定知识库隔离（本期预留字段）。
        tenant_id: 租户 ID（多租户预留，默认单租户 "default"）。
        trace_id: 追踪 ID（跨环节数据血缘）。
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    session_id: str = Field(default="", description="会话 ID，绑定知识库隔离用（M9 预留）")
    tenant_id: str = Field(default="default", description="租户 ID")
    trace_id: Optional[str] = Field(default=None, description="追踪 ID")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="扩展元信息")
