# -*- coding: utf-8 -*-
"""FastAPI 应用入口（application 层主编排装配）。

职责：
    1) 实例化主编排用例 MainOrchestration（内部含 M1 FSM / M2 执行体 / M5+M6 docx），
       挂到 app.state 供控制器依赖注入。
    2) 挂载主编排聚合路由（WriterConsole，/api/v1/console）。
    3) 注册 BizException / 校验 / 兜底异常处理器，统一转 `Result.fail`。

关于业务模块原生 HTTP 路由（M1 / M5+M6）：
    由于共通层 `common.aicoding.dto.Result` 的泛型定义（``Generic[T], BaseModel``）
    不符合 pydantic 2 要求，任何以 ``Result[X]`` 作为返回注解 / response_model 的
    路由（fsm.api / health / tasks）在**模块导入时**即触发
    ``Invalid args for response field``。此为本期共通层契约缺陷，需由 M0/skeleton
    成员修复后，再在本处挂载成员原生路由。当前仅挂载应用层编排路由，
    业务模块通过编排内部函数调用接入（不改动成员产物）。

启动（在 backend 目录）：
    uvicorn application.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from common.aicoding.dto.result import Result
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode

from .controller.writer_console import router as writer_console_router
from .health import router as health_router
from .service.uc_main_orchestration import MainOrchestration
from .tasks import router as tasks_router

logger = logging.getLogger("thesis.application")


def build_app(orchestration: Optional[MainOrchestration] = None) -> FastAPI:
    """构建 FastAPI 应用（主编排闭环）。

    Args:
        orchestration: 预注入的主编排用例（测试可传自定义实例）。
    Returns:
        FastAPI app。
    """
    app = FastAPI(
        title="thesis-agent-dsh",
        description="基于 DSH 的学位论文全流程写作 Agent（一期最小可运行闭环）",
        version="0.1.0",
    )

    # 主编排聚合路由（/api/v1/console）
    app.include_router(writer_console_router)

    # 骨架原生路由（/healthz、/api/v1/tasks）
    app.include_router(health_router)
    app.include_router(tasks_router)

    # 应用级编排单例
    app.state.orchestration = orchestration or MainOrchestration()

    # 异常处理器
    _register_exception_handlers(app)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """注册 BizException / 校验 / 兜底异常处理器。"""

    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
        code = int(exc.code) if exc.code.isdigit() else 0
        payload = Result.fail(code=code, msg=exc.msg, data={"detail": exc.detail})
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = Result.fail(
            code=int(ErrorCode.INVALID_PARAM.value),
            msg=ErrorCode.INVALID_PARAM.default_msg,
            data={"errors": exc.errors()},
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        payload = Result.fail(
            code=int(ErrorCode.SYSTEM_ERROR.value),
            msg=ErrorCode.SYSTEM_ERROR.default_msg,
            data={"err": str(exc)},
        )
        return JSONResponse(status_code=200, content=payload.model_dump())


#: 模块级应用实例（uvicorn application.main:app 直接可启动）。
app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("application.main:app", host="0.0.0.0", port=8000, reload=True)
