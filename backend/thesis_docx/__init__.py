# -*- coding: utf-8 -*-
"""M5/M6 docx（业务包，模块名 thesis_docx）模块：模板解析、生成与校验。

与 `common.aicoding` 契约对齐：
    - Result[T] / BizException / ErrorCode 由 common 或本模块兼容层提供。
本模块按任务契约导出业务路由到 `backend.thesis_docx.router`：
    - POST /api/v1/templates/upload        上传并解析模板
    - GET  /api/v1/templates/{template_id} 模板详情/占位符
    - POST /api/v1/docx/generate           按模板+内容生成 docx
    - POST /api/v1/docx/validate           校验 docx

注意：本包与 pip 的 python-docx 库（顶层名 `docx`）解同名，统一使用
`backend.thesis_docx` 命名空间导入；`import docx` 固定解析到 python-docx 库。
"""
from __future__ import annotations
