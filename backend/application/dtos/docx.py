# -*- coding: utf-8 -*-
"""docx 模板与产出 DTO。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemplateInfo(BaseModel):
    """模板解析信息。"""

    template_id: str = Field(..., description="模板 ID")
    filename: str = Field(default="", description="模板文件名")
    placeholders: List[str] = Field(default_factory=list, description="解析出的占位符列表")
    section_count: int = Field(default=0, description="识别的章节块数量（可选）")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="附加元信息")


class DocxGenerateResult(BaseModel):
    """docx 生成产出。"""

    file_id: str = Field(..., description="生成文件 ID")
    download_url: str = Field(..., description="下载链接")
    filename: str = Field(default="", description="生成文件名")
    content_type: str = Field(
        default="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        description="文件 MIME 类型",
    )
    word_count: int = Field(default=0, description="总字数（可选）")
