# -*- coding: utf-8 -*-
"""M1 FSM 编排器客户端适配器。

封装对 FSM 编排器三个接口的访问：
    - 创建任务      POST {base}/tasks
    - 推进环节      POST {base}/tasks/{task_id}/advance
    - 查询进度      GET  {base}/tasks/{task_id}/progress
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from ..adapters.route_config import ServiceEndpoints


class FsmClient:
    """M1 FSM 编排器客户端。

    Args:
        endpoints: 服务端点配置（默认与当前 app 同进程挂载）。
        client: 可注入的 httpx.AsyncClient（便于测试注入 mock transport）。
    """

    def __init__(
        self,
        endpoints: Optional[ServiceEndpoints] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._endpoints = endpoints or ServiceEndpoints()
        self._client = client

    async def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """创建论文任务，返回任务 DTO（含 task_id）。"""
        url = self._endpoints.url(self._endpoints.routes.fsm_create_task)
        return await self._call("POST", url, json=payload)

    async def advance(self, task_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """推进任务到下一环节。"""
        url = self._endpoints.url(
            self._endpoints.routes.fsm_advance_task.format(task_id=task_id)
        )
        return await self._call("POST", url, json=payload or {})

    async def progress(self, task_id: str) -> Dict[str, Any]:
        """查询任务进度视图。"""
        url = self._endpoints.url(
            self._endpoints.routes.fsm_progress.format(task_id=task_id)
        )
        return await self._call("GET", url)

    async def _call(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        """执行 HTTP 调用并解析 Result 信封，返回 data 字段。"""
        if self._client is not None:
            response = await self._client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 0:
            raise RuntimeError(
                f"FSM 调用失败: {url} -> {body.get('msg', response.text)}"
            )
        return body.get("data") or {}
