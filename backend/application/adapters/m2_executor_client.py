# -*- coding: utf-8 -*-
"""M2 执行体客户端适配器。

封装对 M2 执行体三个环节接口的访问：
    - 环1 选题     POST {base}/rings/1/execute
    - 环5 大纲     POST {base}/rings/5/outline
    - 环6 撰写     POST {base}/rings/6/chapter

各接口统一返回四字段产出：output / accept / fallbackTo / issues / evidence
（详见各环节定义的 RingExecutionResult 结构）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from ..adapters.route_config import ServiceEndpoints


class RingExecutorClient:
    """M2 执行体客户端。

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

    async def execute_ring1(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """环1 选题：返回候选题目集合。"""
        return await self._call(self._endpoints.routes.ring_execute.format(ring_no=1), payload)

    async def outline_ring5(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """环5 大纲：入参选题上下文，返回章节结构。"""
        return await self._call(self._endpoints.routes.ring_outline, payload)

    async def chapter_ring6(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """环6 撰写：入参大纲 / 章节号，返回初稿正文。"""
        return await self._call(self._endpoints.routes.ring_chapter, payload)

    async def _call(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self._endpoints.url(path)
        if self._client is not None:
            response = await self._client.request("POST", url, json=payload)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request("POST", url, json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 0:
            raise RuntimeError(
                f"M2 执行体调用失败: {url} -> {body.get('msg', response.text)}"
            )
        return body.get("data") or {}
