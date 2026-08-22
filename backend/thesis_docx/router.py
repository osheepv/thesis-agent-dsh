# -*- coding: utf-8 -*-
"""M5/M6 docx 业务路由。

导出 `router`（APIRouter），由 application 层探测挂载：
    - POST /api/v1/templates/upload         上传并解析模板
    - GET  /api/v1/templates/{template_id}  模板详情/占位符
    - POST /api/v1/docx/generate            按模板+内容生成 docx
    - POST /api/v1/docx/validate            校验 docx
    - GET  /api/v1/docx/files/{file_id}     下载生成产物（可选）

归属控制：按 session_id 校验模板/文件归属（会话绑定式隔离）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from common.aicoding.dto import Result
from common.aicoding.exception import BizException, ErrorCode

from .dto.base import DocxGenerateRequest, DocxGenerateResult, DocxValidateResult
from .dto.template import TemplateDetailVO, TemplateUploadResult
from .service.docx_service import DocxService

logger = logging.getLogger("thesis.docx")

router = APIRouter(prefix="/api/v1", tags=["M5-M6 docx"])


def get_docx_service(request: Request) -> DocxService:
    """FastAPI 依赖：获取 docx 服务实例。

    优先取 app.state.docx_service；若未注入则创建内存实例（默认单例）。
    """
    service = getattr(request.app.state, "docx_service", None)
    if service is None:
        service = DocxService()
        request.app.state.docx_service = service
    return service


def _fail_code(exc: BizException) -> int:
    """将 6 位字符串错误码转为 int（与 Result.code 对齐）。"""
    return int(exc.code) if exc.code.isdigit() else 0


@router.post("/templates/upload", response_model=Result[TemplateUploadResult])
async def upload_template(
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
    task_id: Optional[int] = Form(default=None),
    service: DocxService = Depends(get_docx_service),
) -> Result[TemplateUploadResult]:
    """上传并解析 docx 模板（安全校验 + 占位符提取 + 骨架识别）。"""
    try:
        if file is None:
            raise BizException(ErrorCode.INVALID_PARAM, "未收到模板文件")
        content = await file.read()
        if not content:
            raise BizException(ErrorCode.INVALID_PARAM, "模板文件为空")
        result = service.upload_template(
            content, file.filename or "template.docx", session_id=session_id, task_id=task_id
        )
        return Result.ok(data=result, msg="模板上传并解析成功")
    except BizException as exc:
        return Result.fail(code=_fail_code(exc), msg=exc.msg, data={"detail": exc.detail})


@router.get("/templates/{template_id}", response_model=Result[TemplateDetailVO])
async def get_template(
    template_id: str,
    session_id: str = "",
    service: DocxService = Depends(get_docx_service),
) -> Result[TemplateDetailVO]:
    """模板详情/占位符（按会话归属校验）。"""
    try:
        detail = service.get_template(template_id, session_id)
        return Result.ok(data=detail)
    except BizException as exc:
        return Result.fail(code=_fail_code(exc), msg=exc.msg, data={"detail": exc.detail})


@router.post("/docx/generate", response_model=Result[DocxGenerateResult])
async def generate_docx(
    req: DocxGenerateRequest,
    service: DocxService = Depends(get_docx_service),
) -> Result[DocxGenerateResult]:
    """按模板+内容生成 docx（生成后校验，不通过则拒绝）。"""
    try:
        result = service.generate(req)
        return Result.ok(data=result, msg="docx 生成成功")
    except BizException as exc:
        return Result.fail(code=_fail_code(exc), msg=exc.msg, data={"detail": exc.detail})


@router.post("/docx/validate", response_model=Result[DocxValidateResult])
async def validate_docx(
    file_id: str,
    session_id: str = "",
    strict: bool = True,
    service: DocxService = Depends(get_docx_service),
) -> Result[DocxValidateResult]:
    """校验 docx（schema/load/roundtrip）。"""
    try:
        result = service.validate(file_id, session_id, strict=strict)
        return Result.ok(data=result, msg="校验完成" if result.is_valid else "校验未通过")
    except BizException as exc:
        return Result.fail(code=_fail_code(exc), msg=exc.msg, data={"detail": exc.detail})


@router.get("/docx/files/{file_id}")
async def download_docx(
    file_id: str,
    session_id: str = "",
    service: DocxService = Depends(get_docx_service),
):
    """下载生成产物（可选，用于 docx.generate 返回的 download_url）。"""
    import os

    from common.aicoding.exception import BizException as _BE

    try:
        output = service._repo.get_output_owned(file_id, session_id)  # noqa: SLF001
        path = output.get("file_path")
        if not path or not os.path.exists(path):
            raise _BE(ErrorCode.NOT_FOUND, "生成文件不存在")
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except BizException as exc:
        return Result.fail(code=_fail_code(exc), msg=exc.msg, data={"detail": exc.detail})
