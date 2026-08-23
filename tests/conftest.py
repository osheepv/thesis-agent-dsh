# -*- coding: utf-8 -*-
"""pytest 公共 fixture：注入项目根与 backend 目录到 sys.path。

- 项目根：使 `backend` 成为顶层包（支撑 executor 的 `from backend.common` 路径）。
- backend： 使 `common` / `fsm` / `application` 可直接导入（支撑 member 的
  `from common.aicoding` 不带前缀路径）。

此外，因成员模块 import 风格不统一（部分用 `backend.X`，部分用 `X`），
为避免同一包被加载为两个模块名（如 `executor` 与 `backend.executor` 各持一份
全局注册表），此处把 backend 下的核心业务包预导入并注册为顶层别名，保证单一
命名空间与单一模块实例。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 测试环境禁用 LLM（不调用 DeepSeek API，执行体自动回退确定性 Mock），
# 环境变量优先于 .env 文件，须在导入业务模块前设置。
os.environ.setdefault("THESIS_DEEPSEEK_ENABLED", "false")
# 测试环境任务存储走内存（不落盘，不污染开发数据库）
os.environ.setdefault("THESIS_TASK_STORE_MEMORY", "true")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

for _p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---- 模块单一命名空间统一（避免同名模块双加载）----
# 源码现为「无前缀」import 风格（`from executor.base` 等），以顶层包为真身；
# 但测试代码仍有少量 `from backend.executor import ...`。为保证单一命名空间，
# 以顶层包为准，并把 backend.<pkg> 及其子模块统一别名为同一模块对象。
import importlib  # noqa: E402

# 注意：不将顶层 `docx` 纳入统一（`docx` 为 pip 的 python-docx 库，site-packages），
# 业务包已更名为 `thesis_docx`，统一到 backend.thesis_docx 保证单一模块实例。
for _name in ("common", "executor", "fsm", "thesis_docx"):
    # 以顶层包为真身（backend 已在 sys.path）
    try:
        importlib.import_module(_name)
    except ImportError:  # pragma: no cover - 部分模块可能未实现
        continue
    top = sys.modules.get(_name)
    if top is None:
        continue
    # 把 backend.<pkg> 以及它的所有子模块统一别名为对应的顶层模块对象，
    # 使带前缀 `from backend.executor import ...` 与无前缀指向同一实例。
    sys.modules[f"backend.{_name}"] = top
    for _mod_name, _mod in list(sys.modules.items()):
        if _mod_name == _name or _mod_name.startswith(_name + "."):
            sys.modules["backend." + _mod_name] = _mod
