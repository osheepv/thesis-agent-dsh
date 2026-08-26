"""数据库模型兼容入口。

历史版本曾在此重复声明 ``t_task`` 和 ``t_fsm_state``，与实际运行时
``fsm.state.orm``互斥。现在只重导出唯一运行时映射；新代码应直接从
``fsm.state.orm``导入。
"""

from fsm.state.orm import (
    AcceptanceGateModel,
    FSMBase,
    FsmStateModel,
    TaskModel,
)


Base = FSMBase
Task = TaskModel
FsmState = FsmStateModel
ALL_MODELS = [TaskModel, FsmStateModel, AcceptanceGateModel]
KB_MODELS: list[type] = []

__all__ = [
    "AcceptanceGateModel",
    "ALL_MODELS",
    "Base",
    "FsmState",
    "FsmStateModel",
    "FSMBase",
    "KB_MODELS",
    "Task",
    "TaskModel",
]
