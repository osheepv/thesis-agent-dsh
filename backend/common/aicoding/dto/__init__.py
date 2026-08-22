# -*- coding: utf-8 -*-
"""公共 DTO（数据传输对象）模块。

包含统一请求/响应/分页数据结构。本模块无外部业务依赖，供各应用层模块复用。
"""
from .base_request import BaseRequest
from .result import Result
from .page import PageRequest, PageResponse

__all__ = ["BaseRequest", "Result", "PageRequest", "PageResponse"]
