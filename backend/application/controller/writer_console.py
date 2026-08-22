# -*- coding: utf-8 -*-
"""写作者工作台聚合路由（WriterConsole）。

把主编排闭环（创建任务 / 模板解析 / 环1选题 / 环5大纲 / 环6撰写 / 生成 docx /
进度）以一组聚合 REST 端点暴露，走 `application.main` 挂载的
`MainOrchestration` 单例。

路径统一挂在 `/api/v1/console` 下，与 M1 的 `/api/v1/tasks`（原生 FSM）错开，
方便写作者按「闭环语义」调用。

所有端点返回 `Result[T]` 信封；`BizException` 由 FastAPI handler 统一转换为
`Result.fail`（见 application.main / app.py 的 exception_handler）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File

from common.aicoding.dto.result import Result
from common.aicoding.enums.degree import Degree

from ..service.uc_main_orchestration import MainOrchestration

router = APIRouter(prefix="/api/v1/console", tags=["WriterConsole"])


def get_orchestration(request: Request) -> MainOrchestration:
    """FastAPI 依赖：获取应用级主编排用例实例（取自 app.state）。"""
    return request.app.state.orchestration


# ---------------------------------------------------------------------
# 创建论文任务（闭环入口）
# ---------------------------------------------------------------------
@router.post("/tasks", response_model=None)
async def create_task(req: Dict[str, Any],
                      orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    title = req.get("title", "")
    degree = req.get("degree", "MASTER")
    subject_field = req.get("subject_field", "")
    template_id = req.get("template_id")
    session_id = req.get("session_id", "")
    tenant_id = req.get("tenant_id", "default")
    try:
        degree = Degree(degree)
    except ValueError:
        return Result.fail(code=2, msg=f"非法学位等级: {degree}", data={"degree": degree})
    return orchestration.create_task(
        title=title, degree=degree, subject_field=subject_field,
        template_id=template_id, session_id=session_id, tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------
# 上传 / 解析模板（可选步骤）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/template", response_model=None)
async def upload_template(task_id: str, file: Optional[UploadFile] = File(default=None),
                          session_id: str = "",
                          orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    if file is None:
        return Result.ok(data=None, msg="未上传模板，跳过解析")
    content = await file.read()
    return orchestration.upload_template(task_id, content, file.filename or "template.docx",
                                         session_id=session_id)


# ---------------------------------------------------------------------
# 环1 选题
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/1/execute", response_model=None)
async def ring1_execute(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring1(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环2 开题评审（新颖度）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/2/review", response_model=None)
async def ring2_review(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring2(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环4 综述评审（创新点包住）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/4/review", response_model=None)
async def ring4_review(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring4(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环5 大纲
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/5/outline", response_model=None)
async def ring5_outline(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring5(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环6 撰写
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/6/chapter", response_model=None)
async def ring6_chapter(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring6(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环3 文献调研
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/3/execute", response_model=None)
async def ring3_execute(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring3(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环7 润色
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/7/polish", response_model=None)
async def ring7_polish(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring7(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环8 引用校验
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/8/validate", response_model=None)
async def ring8_validate(task_id: str, session_id: str = "",
                         orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring8(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环9 排版检查
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/9/layout", response_model=None)
async def ring9_layout(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring9(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环10 定稿汇总
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/10/final", response_model=None)
async def ring10_final(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring10(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 生成 docx
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/docx/generate", response_model=None)
async def generate_docx(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.generate_docx(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 进度
# ---------------------------------------------------------------------
@router.get("/tasks/{task_id}/progress", response_model=None)
async def task_progress(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.progress(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def _err(exc: Exception) -> Result[Any]:
    """把 BizException / 通用异常转 Result.fail（供同步编排缺陷快速返回）。"""
    from common.aicoding.exception.biz_exception import BizException

    if isinstance(exc, BizException):
        code = int(exc.code) if exc.code.isdigit() else 0
        return Result.fail(code=code, msg=exc.msg, data={"detail": exc.detail})
    return Result.fail(code=1, msg=str(exc))
