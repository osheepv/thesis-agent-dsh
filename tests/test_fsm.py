# -*- coding: utf-8 -*-
"""M1 FSM 编排器 + M4 状态存储 单元测试。

覆盖维度（与任务要求一致）：
1. 学位等级路由：本科/硕士/博士在环1创新要求、环4引用深度、环5章节深度上的差异。
2. 状态推进：执行产物进入 WAITING_APPROVAL，确认后才推进。
3. 回退栈：前驱指针 + JSON 快照，rollback 恢复历史状态。
4. 幂等键去重：同 bizReqNo 重复推进不生效。
5. 验收看门：accept 布尔化，拒绝时记录 FALLBACK Gate。
6. FSM 状态快照：snapshot_json / decode_snapshot 往返一致性。

运行方式：在 project 根执行 `pytest tests/test_fsm.py`。
"""
from __future__ import annotations

import pytest

from common.aicoding.enums import Degree, PhaseState, RingType
from common.aicoding.exception import BizException
from fsm.orchestrator import FsmOrchestrator, RING_ORDER
from fsm.repository import InMemoryFsmRepository
from fsm.state.models import FsmState, get_degree_route


@pytest.fixture()
def repo() -> InMemoryFsmRepository:
    return InMemoryFsmRepository()


@pytest.fixture()
def orch(repo: InMemoryFsmRepository) -> FsmOrchestrator:
    return FsmOrchestrator(repo)


@pytest.fixture()
def master_task(orch: FsmOrchestrator) -> FsmState:
    return orch.create_task(
        title="基于大模型的论文写作研究",
        degree=Degree.MASTER,
        subject_field="计算机科学与技术",
        template_id="TPL-001",
    )


def submit_and_advance(
    orch: FsmOrchestrator,
    task_id: str,
    biz_req_no: str,
    accept: bool = True,
    reject_reason: str | None = None,
    artifact: str | None = None,
) -> FsmState:
    """测试辅助：先提交当前环产物，再执行用户确认。"""
    state = orch.get_task(task_id)
    orch.submit_execution(
        task_id,
        artifact or f"doc://ring-{state.current_ring_no}.json",
        accepted=True,
    )
    return orch.advance(
        task_id,
        biz_req_no=biz_req_no,
        accept=accept,
        reject_reason=reject_reason,
    )


# ============================================================
# 1. 学位等级路由
# ============================================================
class TestDegreeRoute:
    def test_ring1_innovation_ascending(self):
        """环1创新要求应随学位层次升高：LOW < MEDIUM < HIGH。"""
        lb = get_degree_route(Degree.BACHELOR, RingType.RING_1).innovation_level.value
        lm = get_degree_route(Degree.MASTER, RingType.RING_1).innovation_level.value
        lp = get_degree_route(Degree.PHD, RingType.RING_1).innovation_level.value
        assert lb == "LOW"
        assert lm == "MEDIUM"
        assert lp == "HIGH"

    def test_ring4_citation_depth_ascending(self):
        """环4综述引用深度应随学位层次升高：20 < 40 < 80。"""
        cb = get_degree_route(Degree.BACHELOR, RingType.RING_4).citation_depth
        cm = get_degree_route(Degree.MASTER, RingType.RING_4).citation_depth
        cp = get_degree_route(Degree.PHD, RingType.RING_4).citation_depth
        assert (cb, cm, cp) == (20, 40, 80)

    def test_ring5_outline_depth_ascending(self):
        """环5大纲章节深度应随学位层次升高：2 < 3 < 4。"""
        db = get_degree_route(Degree.BACHELOR, RingType.RING_5).outline_depth
        dm = get_degree_route(Degree.MASTER, RingType.RING_5).outline_depth
        dp = get_degree_route(Degree.PHD, RingType.RING_5).outline_depth
        assert (db, dm, dp) == (2, 3, 4)

    def test_hitl_sensitive_rings(self):
        """环2/4/8/10 为 HITL 敏感环节，各学位均 hitl_required=True。"""
        for ring in (RingType.RING_2, RingType.RING_4, RingType.RING_8, RingType.RING_10):
            for deg in Degree:
                assert get_degree_route(deg, ring).hitl_required is True

    def test_route_vo_has_ten_rings(self):
        """RouteVO 应包含十环节全程配置。"""
        orch = FsmOrchestrator(InMemoryFsmRepository())
        t = orch.create_task(title="t", degree=Degree.MASTER, subject_field="x")
        route = orch.get_route(t.task_id)
        assert len(route["routes"]) == 10
        assert route["routes"][0]["ring"] == "RING_1"
        assert route["routes"][9]["ring"] == "RING_10"


# ============================================================
# 2. 状态推进
# ============================================================
class TestAdvance:
    def test_advance_ring1_to_ring2(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        assert t.current_ring_no == 1
        assert t.phase_state == PhaseState.NOT_STARTED

        pending = orch.submit_execution(t.task_id, "doc://topic.json", accepted=True)
        assert pending.current_ring_no == 1
        assert pending.phase_state == PhaseState.WAITING_APPROVAL
        st = orch.advance(t.task_id, biz_req_no="R1", accept=True)
        assert st.current_ring_no == 2
        assert st.phase_state == PhaseState.NOT_STARTED
        assert st.hitl_confirmed is False
        assert st.prev_ring_no == 1
        # 主产物指针已记录
        assert st.artifacts["1"] == "doc://topic.json"

    def test_advance_reject_sets_fallback(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        st = submit_and_advance(
            orch, t.task_id, "R1", accept=False, reject_reason="选题范围过大"
        )
        assert st.phase_state == PhaseState.FALLBACK
        assert st.current_ring_no == 1  # 拒绝不推进
        # 看门记录 accepted=False
        gates = orch._repo.gates(t.task_id)
        assert gates and gates[-1].accepted is False

    def test_advance_hitl_confirm(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        submit_and_advance(orch, t.task_id, "R1")
        orch.submit_execution(t.task_id, "doc://ring-2.json", accepted=True)
        st = orch.confirm_hitl(t.task_id, confirmed=True)  # 人工通过 → 推进到环3
        assert st.current_ring_no == 3
        # 环3非HITL → NOT_STARTED
        assert st.phase_state == PhaseState.NOT_STARTED

    def test_advance_past_final_rejected(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        # 一路推进到环10并通过
        for i in range(1, 10):
            submit_and_advance(orch, t.task_id, f"A{i}")
        final = submit_and_advance(orch, t.task_id, "A10")
        assert final.current_ring_no == 10
        assert final.is_finished is True
        # 完结后禁止推进
        with pytest.raises(BizException):
            orch.advance(t.task_id, biz_req_no="A11", accept=True)

    def test_advance_without_execution_rejected(self, orch: FsmOrchestrator, master_task: FsmState):
        with pytest.raises(BizException):
            orch.advance(master_task.task_id, biz_req_no="NO-ARTIFACT", accept=True)


# ============================================================
# 3. 回退栈
# ============================================================
class TestRollback:
    def test_rollback_restores_history(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        # 推进两环：环1→环2
        submit_and_advance(orch, t.task_id, "R1", artifact="doc://c1.json")

        # 推进环2（HITL 需确认，再确认）→ ring3
        orch.submit_execution(t.task_id, "doc://c2.json", accepted=True)
        orch.confirm_hitl(t.task_id, confirmed=True)

        st = orch.get_task(t.task_id)
        assert st.current_ring_no == 3
        assert len(st.rollback_stack) >= 2  # 已压入至少两个快照

        # 回退到环1
        back = orch.rollback(t.task_id, 1)
        assert back.current_ring_no == 1
        assert back.phase_state == PhaseState.NOT_STARTED
        assert back.prev_ring_no is None  # 环1无前驱

    def test_rollback_invalid_target(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        submit_and_advance(orch, t.task_id, "R1")
        # 目标环节 >= 当前环节，应抛错
        with pytest.raises(BizException):
            orch.rollback(t.task_id, 2)
        with pytest.raises(BizException):
            orch.rollback(t.task_id, 0)

    def test_rollback_snapshot_roundtrip(self):
        """快照 serialize/deserialize 往返应保持一致。"""
        st = FsmState(
            task_id="TASK-X",
            current_ring_no=4,
            degree=Degree.PHD,
            prev_ring_no=3,
            phase_state=PhaseState.IN_PROGRESS,
            title="快照往返",
            subject_field="NLP",
            template_id="T9",
            artifacts={"3": "doc://a.json"},
            biz_req_no="SNAP-1",
        )
        snap = st.snapshot_json()
        restored = FsmState.decode_snapshot(snap)
        assert restored.task_id == "TASK-X"
        assert restored.current_ring_no == 4
        assert restored.degree == Degree.PHD
        assert restored.prev_ring_no == 3
        assert restored.phase_state == PhaseState.IN_PROGRESS
        assert restored.artifacts == {"3": "doc://a.json"}


# ============================================================
# 4. 幂等键去重
# ============================================================
class TestIdempotency:
    def test_same_biz_req_no_no_double_advance(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        submit_and_advance(orch, t.task_id, "REQ-1")
        st_state = orch.get_task(t.task_id)
        assert st_state.current_ring_no == 2

        # 同请求号重复调用：不重复推进
        again = orch.advance(t.task_id, biz_req_no="REQ-1", accept=True)
        assert again.current_ring_no == 2  # 仍在环2

    def test_different_biz_req_no_advances(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        # REQ-1：推进环1(HITL非敏感) -> 环2
        submit_and_advance(orch, t.task_id, "REQ-1")
        assert orch.get_task(t.task_id).current_ring_no == 2
        # 环2 是 HITL 敏感，需人工确认后进入环3
        orch.submit_execution(t.task_id, "doc://ring-2.json", accepted=True)
        orch.confirm_hitl(t.task_id, confirmed=True)
        assert orch.get_task(t.task_id).current_ring_no == 3
        # REQ-2：推进环3(非HITL) -> 环4
        submit_and_advance(orch, t.task_id, "REQ-2")
        assert orch.get_task(t.task_id).current_ring_no == 4


# ============================================================
# 5. 创建任务与异常
# ============================================================
class TestCreateTask:
    def test_create_task_initial(self, orch: FsmOrchestrator):
        t = orch.create_task(title="题目", degree=Degree.BACHELOR, subject_field="AI")
        assert t.current_ring_no == 1
        assert t.phase_state == PhaseState.NOT_STARTED
        assert t.degree == Degree.BACHELOR

    def test_create_task_duplicate(self, orch: FsmOrchestrator, master_task: FsmState):
        with pytest.raises(BizException):
            orch.create_task(
                title="重复", degree=Degree.MASTER, subject_field="x", task_id=master_task.task_id
            )

    def test_create_task_empty_title(self, orch: FsmOrchestrator):
        with pytest.raises(BizException):
            orch.create_task(title="", degree=Degree.MASTER, subject_field="x")

    def test_get_task_not_found(self, orch: FsmOrchestrator):
        with pytest.raises(BizException):
            orch.get_task("NON-EXISTENT")


# ============================================================
# 6. 进度视图
# ============================================================
class TestProgress:
    def test_progress_view(self, orch: FsmOrchestrator, master_task: FsmState):
        t = master_task
        submit_and_advance(orch, t.task_id, "R1")
        p = orch.get_progress(t.task_id)
        assert p["total_rings"] == 10
        assert p["current_ring_no"] == 2
        assert len(p["rings"]) == 10
        # 环1 PASSED，环2尚未执行，其余 NOT_STARTED
        assert p["rings"][0]["state"] == PhaseState.PASSED.value
        assert p["rings"][1]["state"] == PhaseState.NOT_STARTED.value
        assert p["can_execute"] is True
        assert p["can_confirm"] is False
        assert p["rings"][9]["state"] == PhaseState.NOT_STARTED.value


# ============================================================
# 7. M4 持久化（SQLite 模拟 PostgreSQL，验证状态+Gate 同事务）
# ============================================================
class TestStatePersistence:
    """M4 状态存储落库回归（SQLite 内存模拟，SQLAlchemy 2.0 ORM）。"""

    def _make_orch(self):
        sqlalchemy = pytest.importorskip("sqlalchemy")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from fsm.state.orm import FSMBase
        from fsm.repository import SqlAlchemyFsmRepository

        engine = create_engine("sqlite:///:memory:")
        FSMBase.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        repo = SqlAlchemyFsmRepository(Session)
        return FsmOrchestrator(repo)

    def test_persist_and_reload_roundtrip(self):
        orch = self._make_orch()
        st = orch.create_task(title="DB", degree=Degree.PHD, subject_field="NLP", template_id="T2")
        # 推进落库
        submit_and_advance(orch, st.task_id, "DB-1", artifact="doc://x.json")
        got = orch.get_task(st.task_id)
        assert got.current_ring_no == 2
        assert got.degree == Degree.PHD  # 枚举从 DB 回读后仍还原
        assert got.artifacts == {"1": "doc://x.json"}
        assert len(got.rollback_stack) == 1

    def test_gate_recorded_in_same_tx(self):
        sqlalchemy = pytest.importorskip("sqlalchemy")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from fsm.state.orm import AcceptanceGateModel, FSMBase
        from fsm.repository import SqlAlchemyFsmRepository

        engine = create_engine("sqlite:///:memory:")
        FSMBase.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        repo = SqlAlchemyFsmRepository(Session)
        orch = FsmOrchestrator(repo)

        st = orch.create_task(title="DB2", degree=Degree.MASTER, subject_field="x")
        submit_and_advance(
            orch, st.task_id, "DB-1", accept=False, reject_reason="驳回"
        )
        with Session() as s:
            gates = s.query(AcceptanceGateModel).filter_by(task_id=st.task_id).all()
            assert len(gates) == 1
            assert gates[0].accepted is False
            assert gates[0].reject_reason == "驳回"

