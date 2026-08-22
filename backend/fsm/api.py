# -*- coding: utf-8 -*-
"""FSM REST API 路由工厂。

本模块提供 `build_fsm_router()`，返回一个可挂载的 APIRouter。

路由清单（对齐 application/adapters/route_config.py 的 M1 契约）：
    POST /tasks                                 创建任务
    GET  /tasks/{task_id}                       任务详情（TaskDetailVO）
    POST /tasks/{task_id}/advance               推进当前环节（bizReqNo 幂等）
    POST /tasks/{task_id}/rollback              回退到目标环节
    GET  /tasks/{task_id}/route                 学位路由参数（RouteVO）
    GET  /tasks/{task_id}/progress              十环节进度
    POST /tasks/{task_id}/hitl/confirm          HITL 人工确认（M3 网关预留）

说明：
    - 默认 `prefix=""`（无 /api/v1 前缀），与骨架 route_config 的 M1 内部服务路由一致，
      供 application 层 FsmClient（ServiceEndpoints.routes）直连。
    - 若要对外暴露带版本前缀的服务，调用 `build_fsm_router(prefix="/api/v1")` 即可。

所有响应统一使用 common.aicoding.dto.Result[T] 信封。
"""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, Path

from common.aicoding.dto import Result
from common.aicoding.enums import Degree
from common.aicoding.exception import BizException, ErrorCode
from fsm.dto import (
    AdvanceRequest,
    ConfirmHitlRequest,
    CreateTaskRequest,
    RollbackRequest,
    RouteVO,
    TaskDetailVO,
)
from fsm.orchestrator import FsmOrchestrator


def _int_code(err: ErrorCode | str) -> int:
    """把 6 位字符串错误码转 int 供 Result.code 使用。"""
    code = err.value if isinstance(err, ErrorCode) else err
    return int(code) if code.isdigit() else 0


def build_fsm_router(
    prefix: str = "",
    orchestrator_provider: Optional[Callable[[], FsmOrchestrator]] = None,
) -> APIRouter:
    """构建 FSM 路由。

    Args:
        prefix: 路由前缀，默认空串（对齐骨架 route_config 的内部路由）。
        orchestrator_provider: 返回 FsmOrchestrator 实例的可调用（依赖注入）。
                               默认空时回退到 fsm.di.get_fsm_orchestrator()。
    """

    def _prov() -> FsmOrchestrator:
        if orchestrator_provider is not None:
            return orchestrator_provider()
        from fsm.di import get_fsm_orchestrator

        return get_fsm_orchestrator()

    router = APIRouter(prefix=prefix, tags=["fsm"])

    def _current_route(state, orchestrator) -> Optional[dict]:
        data = orchestrator.get_route(state.task_id)
        return next((r for r in data["routes"] if r["ring_no"] == state.current_ring_no), None)

    @router.post("/tasks", response_model=None)
    def create_task(
        req: CreateTaskRequest,
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """创建论文任务。"""
        try:
            deg = Degree(req.degree)
        except ValueError:
            raise BizException(ErrorCode.INVALID_PARAM, f"非法学位等级: {req.degree}")
        state = orchestrator.create_task(
            title=req.title,
            degree=deg,
            subject_field=req.subject_field,
            template_id=req.template_id,
        )
        return Result.ok(
            TaskDetailVO.from_state(state, _current_route(state, orchestrator)),
            trace_id=req.trace_id,
            tenant_id=req.tenant_id,
        )

    @router.get("/tasks/{task_id}", response_model=None)
    def get_task(
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """任务详情。"""
        state = orchestrator.get_task(task_id)
        return Result.ok(TaskDetailVO.from_state(state, _current_route(state, orchestrator)))

    @router.post("/tasks/{task_id}/advance", response_model=None)
    def advance(
        body: AdvanceRequest,
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """推进当前环节（bizReqNo 幂等键）。"""
        state = orchestrator.advance(
            task_id=task_id,
            biz_req_no=body.biz_req_no,
            accept=body.accept,
            reject_reason=body.reject_reason,
            artifact_uri=body.artifact_uri,
            gate_rule=body.gate_rule,
        )
        return Result.ok(
            TaskDetailVO.from_state(state, _current_route(state, orchestrator)),
            trace_id=body.trace_id,
            tenant_id=body.tenant_id,
        )

    @router.post("/tasks/{task_id}/rollback", response_model=None)
    def rollback(
        body: RollbackRequest,
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """回退到目标环节。"""
        state = orchestrator.rollback(task_id=task_id, target_ring_no=body.target_ring_no)
        return Result.ok(
            TaskDetailVO.from_state(state, _current_route(state, orchestrator)),
            trace_id=body.trace_id,
            tenant_id=body.tenant_id,
        )

    @router.post("/tasks/{task_id}/hitl/confirm", response_model=None)
    def confirm_hitl(
        body: ConfirmHitlRequest,
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """HITL 人工确认（M3 网关预留，本轮仅落状态）。"""
        state = orchestrator.confirm_hitl(
            task_id=task_id, confirmed=body.confirmed, reject_reason=body.reject_reason
        )
        return Result.ok(
            TaskDetailVO.from_state(state, _current_route(state, orchestrator)),
            trace_id=body.trace_id,
            tenant_id=body.tenant_id,
        )

    @router.get("/tasks/{task_id}/route", response_model=None)
    def get_route(
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """学位路由参数。"""
        data = orchestrator.get_route(task_id)
        return Result.ok(RouteVO(total_rings=10, routes=data["routes"]))

    @router.get("/tasks/{task_id}/progress", response_model=None)
    def get_progress(
        task_id: str = Path(...),
        orchestrator: FsmOrchestrator = Depends(_prov),
    ):
        """十环节进度。"""
        return Result.ok(orchestrator.get_progress(task_id))

    return router


#: 便捷默认实例（无前缀，对齐骨架 route_config 内部服务路由）。
router = build_fsm_router()

#: 带版本前缀的实例（对外示例 API）。
api_v1_router = build_fsm_router(prefix="/api/v1")


def register_exception_handlers(app) -> None:
    """把 BizException 注册为 Result.fail 响应（业务信封用 code 表达错误）。

    挂在应用级（FastAPI 的 exception_handler 属 app，不属 router）。
    生产若由主 app 统管异常，可复用此处逻辑或由 application 层 handler 兜底。
    """
    from fastapi.responses import JSONResponse

    @app.exception_handler(BizException)
    async def _biz_exc_handler(request, exc: BizException):
        code = int(exc.code) if exc.code.isdigit() else exc.code
        payload = Result.fail(code=code, msg=exc.msg, data=exc.to_dict())
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump())
