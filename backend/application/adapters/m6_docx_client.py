# -*- coding: utf-8 -*-
"""M5/M6 docx 客户端适配器。

封装对 docx 模板解析与生成接口的访问：
    - 模板上传/解析  POST {base}/templates/upload
    - docx 生成       POST {base}/docx/generate
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import httpx

from ..adapters.route_config import ServiceEndpoints


class DocxClient:
    """M5/M6 docx 客户端。

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

    async def upload_template(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """上传模板文件并解析占位符，返回 template_id 与占位符列表。"""
        url = self._endpoints.url(self._endpoints.routes.template_upload)
        files = {"file": (filename, file_bytes, content_type)}
        data: Dict[str, str] = {}
        if metadata:
            for key, value in metadata.items():
                if isinstance(value, (str, int, float)):
                    data[key] = str(value)
        if self._client is not None:
            response = await self._client.post(url, files=files, data=data)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, files=files, data=data)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 0:
            raise RuntimeError(
                f"模板上传失败: {url} -> {body.get('msg', response.text)}"
            )
        return body.get("data") or {}

    async def generate(
        self,
        payload: Mapping[str, Any],
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按模板与内容映射生成 docx，返回下载链接。"""
        url = self._endpoints.url(self._endpoints.routes.docx_generate)
        body = dict(payload)
        if template_id is not None:
            body.setdefault("template_id", template_id)
        if self._client is not None:
            response = await self._client.post(url, json=body)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=body)
        response.raise_for_status()
        resp_body = response.json()
        if not isinstance(resp_body, dict) or resp_body.get("code") != 0:
            raise RuntimeError(
                f"docx 生成失败: {url} -> {resp_body.get('msg', response.text)}"
            )
        return resp_body.get("data") or {}
