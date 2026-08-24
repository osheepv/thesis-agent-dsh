"""Fail-closed API 认证、租户隔离、角色授权和安全响应头。"""

from __future__ import annotations

import re
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .models import Principal, UserRole
from .store import AuthorizationError, SecurityStore


_PUBLIC_PATHS = {
    "/healthz", "/api/v1/auth/login", "/api/v1/auth/bootstrap",
    "/docs", "/openapi.json", "/redoc",
}
_TASK_RE = re.compile(r"^/api/v1/console/tasks/([^/]+)")
_NATIVE_TASK_RE = re.compile(r"^/api/v1/tasks(?:/|$)")
_NATIVE_TASK_ID_RE = re.compile(r"^/api/v1/tasks/([^/]+)(?:/|$)")
_KB_RE = re.compile(r"^/api/v1/kb/([^/]+)")
_DOCX_FILE_RE = re.compile(r"^/api/v1/docx/files/([^/]+)$")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, store: SecurityStore, orchestration) -> None:
        super().__init__(app)
        self.store = store
        self.orchestration = orchestration

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "") or f"REQ-{uuid.uuid4().hex[:20]}"
        request.state.request_id = request_id
        request.state.principal = None
        if request.method == "OPTIONS":
            response = await call_next(request)
            return self._secure(response, request_id)
        path = request.url.path
        principal: Principal | None = None
        if self.store.settings.enabled and path not in _PUBLIC_PATHS:
            token = request.cookies.get(self.store.settings.cookie_name, "")
            authorization = request.headers.get("Authorization", "")
            if not token and authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            principal = self.store.authenticate(token)
            if principal is None:
                return self._error(401, "需要登录", request_id)
            request.state.principal = principal
            try:
                self._authorize(request, principal)
            except (AuthorizationError, PermissionError) as exc:
                self.store.audit(
                    tenant_id=principal.tenant_id, user_id=principal.user_id,
                    action="authorization.denied", method=request.method, path=path,
                    status_code=403, request_id=request_id,
                    ip_address=request.client.host if request.client else "",
                )
                return self._error(403, str(exc), request_id)
        response = await call_next(request)
        if self.store.settings.enabled and principal is not None and request.method not in {"GET", "HEAD"}:
            task_match = _TASK_RE.match(path)
            self.store.audit(
                tenant_id=principal.tenant_id, user_id=principal.user_id,
                action="api.mutation", resource_type="task" if task_match else "api",
                resource_id=task_match.group(1) if task_match else "",
                method=request.method, path=path, status_code=response.status_code,
                request_id=request_id,
                ip_address=request.client.host if request.client else "",
            )
        return self._secure(response, request_id)

    def _authorize(self, request: Request, principal: Principal) -> None:
        path, method = request.url.path, request.method
        native_task = _NATIVE_TASK_ID_RE.match(path)
        if native_task:
            self.orchestration.assert_tenant_access(
                native_task.group(1), principal.tenant_id
            )
        elif _NATIVE_TASK_RE.match(path):
            raise AuthorizationError("安全模式下请使用 /api/v1/console/tasks 创建和列出任务")
        task_match = _TASK_RE.match(path)
        if task_match:
            self.orchestration.assert_tenant_access(
                task_match.group(1), principal.tenant_id
            )
        kb_match = _KB_RE.match(path)
        if kb_match:
            self.orchestration.assert_session_tenant(
                kb_match.group(1), principal.tenant_id
            )
        docx_file = _DOCX_FILE_RE.match(path)
        if docx_file:
            service = getattr(self.orchestration, "_docx_service", None)
            record = (
                service._repo.get_output(docx_file.group(1))  # noqa: SLF001
                if service is not None else None
            )
            if record is None:
                raise AuthorizationError("DOCX 文件不存在或无权访问")
            self.orchestration.assert_session_tenant(
                str(record.get("session_id", "")), principal.tenant_id
            )
        elif path.startswith("/api/v1/docx") or path.startswith("/api/v1/templates"):
            raise AuthorizationError("安全模式下请使用论文任务内的模板和 DOCX 工作流接口")
        if method in {"GET", "HEAD"}:
            return
        if method == "DELETE" and principal.role != UserRole.OWNER:
            raise AuthorizationError("只有租户所有者可以删除资源")
        review_action = any(token in path for token in ("/review", "/confirm"))
        if review_action and principal.role in {
            UserRole.OWNER, UserRole.EDITOR, UserRole.REVIEWER
        }:
            return
        if principal.role not in {UserRole.OWNER, UserRole.EDITOR}:
            raise AuthorizationError("当前角色没有写入权限")

    @staticmethod
    def _secure(response, request_id: str):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Request-ID"] = request_id
        return response

    @classmethod
    def _error(cls, status: int, message: str, request_id: str) -> JSONResponse:
        response = JSONResponse(
            status_code=status,
            content={
                "code": status, "msg": message, "data": None,
                "traceId": request_id, "tenantId": "",
            },
        )
        return cls._secure(response, request_id)
