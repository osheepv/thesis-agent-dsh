# -*- coding: utf-8 -*-
"""M5/M6 docx DTO 模块。

包含模板解析、生成请求/响应、校验请求/响应等数据传输对象。
统一采用 pydantic BaseModel；分页/信封复用 common.aicoding.dto。
"""
from __future__ import annotations

from typing import Any, Optional

from .base import (
    DocxGenerateRequest,
    DocxGenerateResult,
    DocxValidateRequest,
    DocxValidateResult,
    SectionSkeleton,
    TemplateParseVO,
)
from .template import TemplateDetailVO, TemplateUploadResult

__all__ = [
    "DocxGenerateRequest",
    "DocxGenerateResult",
    "DocxValidateRequest",
    "DocxValidateResult",
    "SectionSkeleton",
    "TemplateParseVO",
    "TemplateDetailVO",
    "TemplateUploadResult",
]
