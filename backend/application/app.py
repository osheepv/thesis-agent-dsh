# -*- coding: utf-8 -*-
"""FastAPI 应用装配（聚合入口）。

`create_app()` 由 application.main 提供，此处作为兼容别名导出，供 uvicorn /
pytest 使用。应用级装配与编排单例见 ``application.main.build_app``。
"""
from __future__ import annotations

from .main import build_app as create_app

app = create_app()
