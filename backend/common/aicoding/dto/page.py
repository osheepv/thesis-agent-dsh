# -*- coding: utf-8 -*-
"""分页请求与响应对象。"""
from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageRequest(BaseModel):
    """分页请求对象。

    Attributes:
        page: 页码，从 1 开始。
        size: 每页条数。
    """

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    size: int = Field(default=20, ge=1, le=500, description="每页条数")
    keyword: Optional[str] = Field(default=None, description="模糊搜索关键词")


class PageResponse(BaseModel, Generic[T]):
    """分页响应对象。"""

    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    size: int = Field(default=20, description="每页条数")
    items: List[T] = Field(default_factory=list, description="数据列表")
