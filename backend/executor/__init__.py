# -*- coding: utf-8 -*-
"""M2 环节执行体模块。

组织约定：
- :mod:`executor.base`：统一接口（ExecResult/ExecContext/RingExecutor）与注册表。
- :mod:`executor.ring1_topic`：环1 选题执行体。
- :mod:`executor.ring5_outline`：环5 大纲生成执行体。
- :mod:`executor.ring6_chapter`：环6 分章撰写执行体。
- ring2/3/4/7/8/9/10 为预留目录（skeleton），其中 2/4/8/10 标注 HITL 网关（本期仅留接口）。

真实 DSH（LLM/检索）为二期接入点，本期各环执行体使用确定性 Mock 生成器保证闭环可运行。
"""
from .base import EXECUTOR_REGISTRY, ExecContext, ExecResult, RingExecutor, get_executor, register_executor

# 显式 import 触发 register_executor 装饰器，保证注册表填入。
from . import ring1_topic  # noqa: F401
from . import ring2  # noqa: F401
from . import ring3  # noqa: F401
from . import ring4  # noqa: F401
from . import ring5_outline  # noqa: F401
from . import ring6_chapter  # noqa: F401
from . import ring7  # noqa: F401
from . import ring8  # noqa: F401

__all__ = [
    "EXECUTOR_REGISTRY",
    "ExecContext",
    "ExecResult",
    "RingExecutor",
    "get_executor",
    "register_executor",
]
