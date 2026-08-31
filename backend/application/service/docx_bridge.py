# -*- coding: utf-8 -*-
"""DOCX 渲染端口与生产实现（从 uc_main_orchestration.py 拆出）。

DocxRenderPort 是 M5/M6 的抽象端口；RealDocxRenderer 是惰性导入的生产实现。
测试可注入 mock 避免对真实 docxtpl 的依赖。
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode


@runtime_checkable
class DocxRenderPort(Protocol):
    """docx 模板解析与生成端口。"""

    def upload_template(self, file_bytes: bytes, filename: str, **meta: Any) -> Dict[str, Any]:
        """解析模板占位符，返回 {template_id, placeholders, ...}。"""
        ...

    def generate(self, template_id: str, content: Dict[str, Any], **meta: Any) -> Dict[str, Any]:
        """按模板 + 内容生成 docx，返回 {file_id, download_url, ...}。"""
        ...


class RealDocxRenderer:
    """生产实现：包装 M5 parser 与 M6 generator（惰性导入）。

    注意：业务包 `backend.thesis_docx` 已与 pip 的 python-docx 库（顶层名 `docx`）
    解同名。`import docx` 固定解析到 site-packages 的 python-docx 库；业务包
    使用 `backend.thesis_docx` 命名空间导入。本处惰性导入，构造时不触碰业务包，
    仅当真正执行「解析/生成」时才 import；测试注入 mock 时不会触发。

    Args:
        repository: 可选，M6 DocxRepository。提供时生成成功后注册记录，
            供 `/api/v1/docx/files/{file_id}` 下载端点查询（与业务路由共享）。
    """

    def __init__(self, repository=None) -> None:
        self._parser = None
        self._generator = None
        self._validator = None
        self._repository = repository

    def _ensure(self) -> None:
        if self._parser is not None and self._generator is not None and self._validator is not None:
            return
        # 业务包 backend.thesis_docx（已与 pip 的 python-docx 库解同名）。
        from thesis_docx.parser.template_parser import TemplateParser
        from thesis_docx.generator.docx_generator import DocxGenerator
        from thesis_docx.validator.docx_validator import DocxValidator

        if self._parser is None:
            self._parser = TemplateParser()
        if self._generator is None:
            self._generator = DocxGenerator()
        if self._validator is None:
            self._validator = DocxValidator(getattr(self._generator, "_config", None))

    def upload_template(self, file_bytes: bytes, filename: str, **meta: Any) -> Dict[str, Any]:
        self._ensure()
        outcome = self._parser.validate_and_parse(file_bytes, filename)
        return {
            "template_id": meta.get("template_id", f"TPL-{uuid.uuid4().hex[:12].upper()}"),
            "filename": filename,
            "placeholders": outcome.placeholders,
            "section_count": len(outcome.skeleton),
        }

    def generate(self, template_id: str, content: Dict[str, Any], **meta: Any) -> Dict[str, Any]:
        self._ensure()
        template_path = meta.get("template_path", "")
        if not template_path:
            # 未提供用户模板时回退到内置论文模板（含标准占位符），兑现
            # 「无模板也能生成」的契约。注意：python-docx 内置 default.docx 是
            # 空模板（无占位符），渲染出来是空壳；这里改用本仓库内置模板。
            from thesis_docx.config import DocxConfig

            template_path = str(DocxConfig.BUILTIN_TEMPLATE_PATH)
            if not os.path.exists(template_path):
                raise BizException(
                    ErrorCode.DOCX_GENERATE_FAILED,
                    msg="生成 docx 需要模板落盘路径（template_path）",
                    detail={"template_id": template_id, "fallback": template_path},
                )
        outcome = self._generator.render(
            template_path=template_path,
            content=content,
            filename=meta.get("filename"),
        )
        validation = self._validator.validate(outcome.file_path, strict=False)
        if not validation.is_valid:
            try:
                os.remove(outcome.file_path)
            except OSError:
                pass
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED,
                msg="生成 DOCX 未通过基础 OOXML/load/round-trip 校验",
                detail={"errors": validation.errors[:10]},
            )
        # 与业务 DocxService 共享仓储时注册生成记录，下载端点才能找到产物
        if self._repository is not None:
            self._repository.save_output(
                {
                    "file_id": outcome.filename,
                    "session_id": meta.get("session_id", ""),
                    "file_path": outcome.file_path,
                    "filename": outcome.filename,
                    "word_count": outcome.word_count,
                    "template_id": template_id,
                    "cross_references": outcome.cross_reference_report,
                }
            )
        return {
            "file_id": f"FILE-{uuid.uuid4().hex[:12].upper()}",
            "download_url": f"/api/v1/docx/files/{outcome.filename}",
            "filename": outcome.filename,
            "word_count": outcome.word_count,
            "file_path": getattr(outcome, "file_path", ""),
            "cross_references": outcome.cross_reference_report,
            "validation": {
                "is_valid": validation.is_valid,
                "schema_valid": validation.schema_valid,
                "load_valid": validation.load_valid,
                "roundtrip_valid": validation.roundtrip_valid,
                "cross_reference_valid": validation.cross_reference_valid,
                "error_count": validation.error_count,
            },
        }
