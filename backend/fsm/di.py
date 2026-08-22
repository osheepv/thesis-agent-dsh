# -*- coding: utf-8 -*-
"""FSM 应用依赖容器（轻量 DI）。

提供 FsmOrchestrator 单例的获取/覆盖，供 FastAPI Depends 与测试注入。

生产环境：由 application 层启动时调用 configure(orchestrator) 注入真实实例
（内部使用 SqlAlchemyFsmRepository + PostgreSQL session_factory）。

测试环境：可调用 configure(InMemoryFsmRepository) 或直接 set_for_test(repo) 覆盖。
"""
from __future__ import annotations

from typing import Optional

from fsm.orchestrator import FsmOrchestrator
from fsm.repository import FsmRepository

#: 全局单例（惰性初始化，默认内存仓储，生产由 configure 覆盖）。
_orchestrator: Optional[FsmOrchestrator] = None


def configure(repository: FsmRepository) -> FsmOrchestrator:
    """配置全局 FsmOrchestrator（生产启动时调用一次）。"""
    global _orchestrator
    _orchestrator = FsmOrchestrator(repository)
    return _orchestrator


def get_fsm_orchestrator() -> FsmOrchestrator:
    """获取全局 FsmOrchestrator；未配置时回退为内存仓储（便于独立预览/测试）。"""
    global _orchestrator
    if _orchestrator is None:
        from fsm.repository import InMemoryFsmRepository

        _orchestrator = FsmOrchestrator(InMemoryFsmRepository())
    return _orchestrator


def reset() -> None:
    """重置全局实例（测试隔离用）。"""
    global _orchestrator
    _orchestrator = None
