# -*- coding: utf-8 -*-
"""统一响应包装结果对象。

`Result[T]` 是全部 API 与内部服务返回的统一信封：
    code   业务状态码（0 表示成功，非 0 见 ErrorCode）
    msg    可读描述
    data   泛型数据体
    traceId  追踪 ID（跨环节数据血缘）
    tenantId 租户 ID（多租户预留）
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    """统一响应包装。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: int = Field(default=0, description="业务状态码，0 为成功")
    msg: str = Field(default="ok", description="读信息")
    data: Optional[T] = Field(default=None, description="数据体")
    traceId: Optional[str] = Field(default=None, description="追踪 ID")
    tenantId: str = Field(default="default", description="租户 ID")

    @classmethod
    def ok(cls, data: Optional[T] = None, msg: str = "ok", trace_id: Optional[str] = None,
           tenant_id: str = "default") -> "Result[T]":
        """构建成功响应。"""
        return cls(code=0, msg=msg, data=data, traceId=trace_id, tenantId=tenant_id)

    @classmethod
    def fail(cls, code: int, msg: str, trace_id: Optional[str] = None,
             tenant_id: str = "default", data: Optional[Any] = None) -> "Result[T]":
        """构建失败响应。"""
        return cls(code=code, msg=msg, data=data, traceId=trace_id, tenantId=tenant_id)

    @property
    def is_ok(self) -> bool:
        """是否成功。"""
        return self.code == 0
