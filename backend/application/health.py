# -*- coding: utf-8 -*-
"""健康检查路由。"""
from __future__ import annotations

from fastapi import APIRouter

from common.aicoding.dto import Result

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> Result[dict]:
    """健康检查，返回服务与时间戳。"""
    import datetime

    return Result.ok(
        data={
            "service": "thesis-agent-dsh",
            "status": "UP",
            "ts": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        }
    )
