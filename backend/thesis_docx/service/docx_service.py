# -*- coding: utf-8 -*-
"""M5/M6 docx 服务编排。

职责：
    - M5 模板上传：安全校验 -> 随机重命名落盘 -> 解析占位符/骨架 -> 落库；
    - M5 模板详情：按 session 归属返回占位符与骨架；
    - M6 生成：读取模板 -> docxtpl 渲染 -> 生成后校验 -> 拒绝交付/回退；
    - M6 校验：对输出文件做 openxml-audit 多层校验。

安全约定：
    - 模板文件随机重命名存储（`<uuid>.docx`），屏蔽原始可执行文件风险；
    - 所有按 ID 访问均校验 session 归属（会话绑定式隔离，对齐 RBAC）。
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
from typing import Any, Dict, List, Mapping, Optional

from common.aicoding.exception import BizException, ErrorCode

from ..config import DocxConfig
from ..dto.base import (
    DocxGenerateRequest,
    DocxGenerateResult,
    DocxValidateResult,
    TemplateParseVO,
)
from ..dto.template import TemplateDetailVO, TemplateUploadResult
from ..generator import DocxGenerator
from ..parser import TemplateParser
from ..repository import DocxRepository, TemplateRecordDict
from ..validator import DocxValidator


class DocxService:
    """M5/M6 docx 服务。

    Args:
        config: docx 模块配置。
        repository: 存储仓库（默认内存，可注入 SQLAlchemy）。
        parser: 模板解析器。
        generator: docx 生成器。
        validator: docx 校验器。
    """

    def __init__(
        self,
        config: Optional[DocxConfig] = None,
        repository: Optional[DocxRepository] = None,
        parser: Optional[TemplateParser] = None,
        generator: Optional[DocxGenerator] = None,
        validator: Optional[DocxValidator] = None,
    ) -> None:
        self._config = config or DocxConfig()
        self._repo = repository or DocxRepository(self._config)
        self._parser = parser or TemplateParser(self._config)
        self._generator = generator or DocxGenerator(self._config)
        self._validator = validator or DocxValidator(self._config)

    # ================================================================== #
    # M5 模板上传
    # ================================================================== #
    def upload_template(
        self, file_bytes: bytes, original_name: str, session_id: str = "", task_id: Optional[int] = None
    ) -> TemplateUploadResult:
        """上传并解析模板。

        Args:
            file_bytes: 模板二进制。
            original_name: 原始文件名。
            session_id: 会话 ID（绑定式隔离）。
            task_id: 关联任务 ID（可选）。

        Returns:
            TemplateUploadResult。

        Raises:
            BizException: 安全校验失败或解析失败。
        """
        # 1) 安全校验 + 解析
        outcome = self._parser.validate_and_parse(file_bytes, original_name)

        # 2) 随机重命名落盘
        stored_path = self._store_template_bytes(file_bytes, original_name)

        # 3) 计算哈希
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # 4) 组装并落库
        template_id = uuid.uuid4().hex
        rec = self._repo.save_template(
            {
                "template_id": template_id,
                "session_id": session_id,
                "task_id": task_id,
                "template_name": original_name,
                "file_path": stored_path,
                "file_hash": file_hash,
                "file_size": len(file_bytes),
                "parse_status": "PARSED",
                "placeholders": outcome.placeholders,
                "skeleton_sections": [
                    s.model_dump() if hasattr(s, "model_dump") else dict(s)
                    for s in outcome.skeleton
                ],
            }
        )
        return TemplateUploadResult(
            template_id=template_id,
            template_name=original_name,
            filename=original_name,
            placeholders=outcome.placeholders,
            section_count=len(outcome.skeleton),
            parse_status=rec.get("parse_status", "PARSED"),
            file_hash=file_hash,
            meta={"skeleton_sections": [s.model_dump() for s in outcome.skeleton]},
        )

    # ================================================================== #
    # M5 模板详情
    # ================================================================== #
    def get_template(self, template_id: str, session_id: str = "") -> TemplateDetailVO:
        """模板详情/占位符（按会话归属校验）。"""
        rec = self._repo.get_template_owned(template_id, session_id)
        placeholders: List[str] = rec.get("placeholders") or []
        skeleton = rec.get("skeleton_sections") or []
        return TemplateDetailVO(
            template_id=template_id,
            template_name=rec.get("template_name", ""),
            session_id=rec.get("session_id", ""),
            placeholders=placeholders,
            placeholders_detail={"count": len(placeholders), "items": placeholders},
            skeleton_sections=skeleton,
            parse_status=rec.get("parse_status", "PARSED"),
            created_at=rec.get("created_at"),
        )

    # ================================================================== #
    # M6 生成
    # ================================================================== #
    def generate(self, req: DocxGenerateRequest) -> DocxGenerateResult:
        """按模板+内容生成 docx（生成后即校验，不通过拒绝交付）。"""
        rec = self._repo.get_template_owned(req.template_id, req.session_id)
        template_path = rec.get("file_path")
        template_name = rec.get("template_name", "template")
        placeholders: List[str] = rec.get("placeholders") or []

        outcome = self._generator.render(
            template_path=template_path,
            content=req.content,
            template_placeholders=placeholders,
            filename=req.filename,
        )

        # 生成后校验
        validate_outcome = self._validator.validate(outcome.file_path, strict=True)
        validate_vo = self._to_validate_vo(validate_outcome)

        if not validate_vo.is_valid:
            # 拒绝交付：遗留产物清理，抛出业务异常触发上层回退
            self._cleanup_artifact(outcome.file_path)
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED,
                f"生成 docx 未通过校验（errors={validate_vo.error_count}），已拒绝交付",
                detail={"errors": validate_vo.errors[:10], "missing_keys": outcome.missing_keys},
            )

        file_id = uuid.uuid4().hex
        download_url = f"/api/v1/docx/files/{file_id}"
        self._repo.save_output(
            {
                "file_id": file_id,
                "session_id": req.session_id,
                "file_path": outcome.file_path,
                "filename": outcome.filename,
                "word_count": outcome.word_count,
                "template_id": req.template_id,
                "validate": validate_vo.model_dump(),
            }
        )
        return DocxGenerateResult(
            file_id=file_id,
            download_url=download_url,
            filename=outcome.filename,
            word_count=outcome.word_count,
            file_hash=self._sha256_of_file(outcome.file_path),
            validate=validate_vo,
        )

    # ================================================================== #
    # M6 校验（独立接口）
    # ================================================================== #
    def validate(self, file_id: str, session_id: str = "", strict: bool = True) -> DocxValidateResult:
        """校验 docx（对已生成的输出文件）。"""
        output = self._repo.get_output_owned(file_id, session_id)
        path = output.get("file_path")
        outcome = self._validator.validate(path, strict=strict)
        vo = self._to_validate_vo(outcome)
        vo.file_id = file_id
        return vo

    # ================================================================== #
    # 内部工具
    # ================================================================== #
    def _store_template_bytes(self, file_bytes: bytes, original_name: str) -> str:
        """将模板字节以随机重命名落盘并返回路径。"""
        self._config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ext = ".docx"
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = self._config.UPLOAD_DIR / filename
        with open(dest, "wb") as fh:
            fh.write(file_bytes)
        return str(dest)

    @staticmethod
    def _to_validate_vo(outcome: Any) -> DocxValidateResult:
        """将 ValidateOutcome 转为 DocxValidateResult VO。"""
        return DocxValidateResult(
            is_valid=outcome.is_valid,
            schema_valid=outcome.schema_valid,
            load_valid=outcome.load_valid,
            roundtrip_valid=outcome.roundtrip_valid,
            error_count=outcome.error_count,
            warning_count=outcome.warning_count,
            errors=outcome.errors,
            warnings=outcome.warnings,
            validator=outcome.validator,
        )

    @staticmethod
    def _cleanup_artifact(path: str) -> None:
        """清理校验不通过的遗留产物。"""
        import os

        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:  # noqa: BLE001
            pass

    @staticmethod
    def _sha256_of_file(path: str) -> str:
        """计算文件 SHA-256。"""
        import os

        if not path or not os.path.exists(path):
            return ""
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
