# -*- coding: utf-8 -*-
"""健康检查路由。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from common.aicoding.dto import Result

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz(request: Request) -> Result[dict]:
    """健康检查，返回服务与时间戳。"""
    import datetime

    reconciliation = getattr(request.app.state, "startup_reconciliation", {}) or {}
    return Result.ok(
        data={
            "service": "deep-thesis",
            "status": "UP",
            "reconciliation_status": reconciliation.get("status", "UNKNOWN"),
            "inconsistent_task_count": int(
                reconciliation.get("inconsistent_task_count", 0) or 0
            ),
            "global_issue_count": len(reconciliation.get("global_issues", []) or []),
            "ts": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        }
    )
