# -*- coding: utf-8 -*-
"""服务启动入口。

用法:
    cd backend
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from application.app import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
