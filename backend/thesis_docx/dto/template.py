# -*- coding: utf-8 -*-
"""模板上传/详情 DTO。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .base import SectionSkeleton


class TemplateUploadResult(BaseModel):
    """模板上传接口响应（对齐 DocxClient 期望）。

    Attributes:
        template_id: 模板 ID。
        template_name: 模板文件名。
        filename: 别名（与 template_name 同，兼容调用方）。
        placeholders: 占位符列表。
        section_count: 骨架章节数量。
        parse_status: 解析状态。
        file_hash: 文件 SHA-256。
        meta: 附加元信息。
    """

    template_id: str = Field(..., description="模板 ID")
    template_name: str = Field(default="", description="模板文件名")
    filename: str = Field(default="", description="模板文件名（兼容别名）")
    placeholders: List[str] = Field(default_factory=list, description="占位符列表")
    section_count: int = Field(default=0, description="骨架章节数量")
    parse_status: str = Field(default="PARSED", description="解析状态")
    file_hash: str = Field(default="", description="文件 SHA-256")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="附加元信息")


class TemplateDetailVO(BaseModel):
    """模板详情接口响应。

    Attributes:
        template_id: 模板 ID。
        template_name: 模板文件名。
        session_id: 会话 ID。
        placeholders: 占位符列表。
        placeholders_detail: 占位符->出现位置（阶段/区域）。
        skeleton_sections: 骨架章节结构。
        parse_status: 解析状态。
        created_at: 创建时间（可选）。
    """

    template_id: str = Field(..., description="模板 ID")
    template_name: str = Field(default="", description="模板文件名")
    session_id: str = Field(default="", description="会话 ID")
    placeholders: List[str] = Field(default_factory=list, description="占位符列表")
    placeholders_detail: Optional[Dict[str, Any]] = Field(
        default=None, description="占位符->出现位置"
    )
    skeleton_sections: List[SectionSkeleton] = Field(
        default_factory=list, description="骨架章节结构"
    )
    parse_status: str = Field(default="PARSED", description="解析状态")
    created_at: Optional[str] = Field(default=None, description="创建时间（ISO）")
