"""认证、用户管理与审计 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from common.aicoding.dto.result import Result

from .models import Principal, UserRole
from .store import AuthenticationError, AuthorizationError, SecurityStore


router = APIRouter(prefix="/api/v1/auth", tags=["security"])


def _store(request: Request) -> SecurityStore:
    return request.app.state.security_store


def _principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthenticationError("未认证")
    return principal


@router.post("/bootstrap", response_model=None)
async def bootstrap(request: Request, req: dict[str, Any]) -> Result[Any]:
    try:
        data = _store(request).bootstrap_owner(
            tenant_name=str(req.get("tenant_name", "")),
            username=str(req.get("username", "")),
            password=str(req.get("password", "")),
            bootstrap_token=request.headers.get("X-Bootstrap-Token", ""),
        )
        return Result.ok(data=data, msg="租户所有者初始化成功")
    except AuthenticationError:
        return Result.fail(code=401, msg="初始化失败")


@router.post("/login", response_model=None)
async def login(request: Request, response: Response, req: dict[str, Any]) -> Result[Any]:
    store = _store(request)
    try:
        token, principal = store.login(
            str(req.get("username", "")),
            str(req.get("password", "")),
            request.client.host if request.client else "",
        )
    except AuthenticationError:
        return Result.fail(code=401, msg="用户名或密码无效")
    response.set_cookie(
        key=store.settings.cookie_name,
        value=token,
        max_age=store.settings.session_hours * 3600,
        httponly=True,
        secure=store.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return Result.ok(data=principal.to_dict(), msg="登录成功")


@router.post("/logout", response_model=None)
async def logout(request: Request, response: Response) -> Result[Any]:
    principal = _principal(request)
    store = _store(request)
    store.logout(principal)
    response.delete_cookie(
        store.settings.cookie_name,
        path="/",
        httponly=True,
        secure=store.settings.cookie_secure,
        samesite="lax",
    )
    return Result.ok(msg="已退出登录")


@router.get("/me", response_model=None)
async def me(request: Request) -> Result[Any]:
    return Result.ok(data=_principal(request).to_dict(), msg="当前用户")


@router.post("/users", response_model=None)
async def create_user(request: Request, req: dict[str, Any]) -> Result[Any]:
    try:
        role = UserRole(str(req.get("role", "VIEWER")))
        data = _store(request).create_user(
            principal=_principal(request),
            username=str(req.get("username", "")),
            password=str(req.get("password", "")),
            role=role,
        )
        return Result.ok(data=data, msg="用户已创建")
    except (AuthenticationError, AuthorizationError, ValueError) as exc:
        return Result.fail(code=403, msg=str(exc))


@router.get("/audit", response_model=None)
async def audit(request: Request, limit: int = 200) -> Result[Any]:
    try:
        return Result.ok(
            data=_store(request).list_audit(_principal(request), limit=limit),
            msg="操作审计日志",
        )
    except AuthorizationError as exc:
        return Result.fail(code=403, msg=str(exc))
