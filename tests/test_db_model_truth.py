"""数据库映射只能存在一个FSM事实源。"""

from db.models import ALL_MODELS, Base, FsmState, Task
from fsm.state.orm import AcceptanceGateModel, FSMBase, FsmStateModel, TaskModel


def test_fsm_table_is_owned_only_by_runtime_metadata():
    assert Base is FSMBase
    assert FsmState is FsmStateModel
    assert Task is TaskModel
    assert FSMBase.metadata.tables["t_fsm_state"] is FsmStateModel.__table__


def test_legacy_business_models_do_not_reference_removed_fsm_mapper():
    assert ALL_MODELS == [TaskModel, FsmStateModel, AcceptanceGateModel]
    assert set(Base.metadata.tables) == {"t_task", "t_fsm_state", "t_acceptance_gate"}
