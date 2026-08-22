# -*- coding: utf-8 -*-
"""M1 FSM 编排器 —— FsmOrchestrator。

职责（对齐系统设计 §3.2.M1.2）：
    1. 维护十环节状态机（RingType.RING_1..RING_10）。
    2. 学位等级路由：本科/硕士/博士在环节阈值、创新要求、引用深度上的差异，
       通过 DegreeRoute 参数表体现（fsm/state/models.py 的 DEGREE_ROUTE_TABLE）。
    3. 回退栈：前驱指针 + JSON 快照（RollbackEntry）。
    4. 验收看门：每环节 return 布尔化 accept（AcceptanceGate）。

事务边界：状态推进/回退均通过 repository.persist_transition（FSM + Gate 同事务）。

HITL 说明：环2/4/8/10 为 HITL 敏感环节，阶段态为 IN_PROGRESS 时等待人工确认；
M3 网关负责确认，本轮仅在 FsmOrchestrator 预留 confirm_hitl 接口与 hitl_required 标志。
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from common.aicoding.enums import Degree, PhaseState, RingType
from common.aicoding.exception import BizException, ErrorCode
from fsm.repository import FsmRepository
from fsm.state.models import (
    AcceptanceGate,
    DegreeRoute,
    FsmState,
    RollbackEntry,
    get_degree_route,
)

#: 十环节顺序（从环1到环10）。
RING_ORDER: list[RingType] = [
    RingType.RING_1,
    RingType.RING_2,
    RingType.RING_3,
    RingType.RING_4,
    RingType.RING_5,
    RingType.RING_6,
    RingType.RING_7,
    RingType.RING_8,
    RingType.RING_9,
    RingType.RING_10,
]

#: 环节号 → RingType 便捷映射（RingType.RING_1 等，值如 "RING_1"，编号取末段数字）。
RING_NO_TO_TYPE: dict[int, RingType] = {
    int(rt.value.split("_")[-1]): rt for rt in RING_ORDER
}
#: RingType → 环节号映射。
RING_TYPE_TO_NO: dict[RingType, int] = {
    rt: int(rt.value.split("_")[-1]) for rt in RING_ORDER
}


def _new_task_id() -> str:
    """生成任务 ID（本期用 UUID，生产可替换为雪花 ID）。"""
    return f"TASK-{uuid.uuid4().hex[:12].upper()}"


class FsmOrchestrator:
    """FSM 编排器。"""

    def __init__(self, repository: FsmRepository) -> None:
        if repository is None:
            raise ValueError("repository 不能为 None")
        self._repo = repository

    # ============================================================
    # 创建任务
    # ============================================================
    def create_task(
        self,
        title: str,
        degree: Degree,
        subject_field: str = "",
        template_id: str = "",
        task_id: Optional[str] = None,
    ) -> FsmState:
        """创建论文任务并初始化 FSM（默认停在环1、未开始）。

        Raises:
            BizException: 参数非法 / 任务已存在。
        """
        if not title:
            raise BizException(ErrorCode.INVALID_PARAM, "论文题目不能为空")
        if not isinstance(degree, Degree):
            raise BizException(ErrorCode.INVALID_PARAM, "学位等级非法")

        final_task_id = task_id or _new_task_id()
        existing = self._repo.get_by_task_id(final_task_id)
        if existing is not None:
            raise BizException(ErrorCode.TASK_ALREADY_EXISTS, f"任务已存在: {final_task_id}")

        state = FsmState(
            task_id=final_task_id,
            current_ring_no=1,
            degree=degree,
            prev_ring_no=None,
            rollback_stack=[],
            phase_state=PhaseState.NOT_STARTED,
            title=title,
            subject_field=subject_field,
            template_id=template_id,
            hitl_confirmed=False,
            artifacts={},
            aux_artifacts={},
        )
        self._repo.persist_transition(state)
        return state

    # ============================================================
    # 读取任务（TaskDetailVO）
    # ============================================================
    def get_task(self, task_id: str) -> FsmState:
        """读取任务 FSM 状态。

        Raises:
            BizException: 任务不存在。
        """
        state = self._repo.get_by_task_id(task_id)
        if state is None:
            raise BizException(ErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}")
        return state

    # ============================================================
    # 学位路由
    # ============================================================
    def get_route(self, task_id: str) -> dict[str, Any]:
        """返回任务的学位路由参数（RouteVO），含十环节逐环节配置。"""
        state = self.get_task(task_id)
        return self._build_route_vo(state)

    def _build_route_vo(self, state: FsmState) -> dict[str, Any]:
        degree = state.degree
        routes: list[dict[str, Any]] = []
        for ring in RING_ORDER:
            route: DegreeRoute = get_degree_route(degree, ring)
            routes.append(
                {
                    "ring": ring.value,
                    "ring_no": RING_TYPE_TO_NO[ring],
                    "label": ring.label,
                    "innovation_level": route.innovation_level.value,
                    "citation_depth": route.citation_depth,
                    "outline_depth": route.outline_depth,
                    "required_outline_levels": route.required_outline_levels,
                    "hitl_required": route.hitl_required,
                    "min_word_requirement": route.min_word_requirement,
                    "is_hitl_gate": ring.is_hitl_gate,
                }
            )
        return {
            "task_id": state.task_id,
            "degree": degree.value,
            "degree_label": degree.label,
            "current_ring_no": state.current_ring_no,
            "overall_min_word": degree.min_word_requirement,
            "routes": routes,
        }

    # ============================================================
    # 进度（ProgressVO）
    # ============================================================
    def get_progress(self, task_id: str) -> dict[str, Any]:
        """返回十环节进度。"""
        state = self.get_task(task_id)

        rings: list[dict[str, Any]] = []
        for no, ring in enumerate(RING_ORDER, start=1):
            if no < state.current_ring_no or (
                no == state.current_ring_no and state.phase_state == PhaseState.PASSED
            ):
                st = PhaseState.PASSED
            elif no == state.current_ring_no:
                st = state.phase_state
            else:
                st = PhaseState.NOT_STARTED

            route = get_degree_route(state.degree, ring)
            rings.append(
                {
                    "ring_no": no,
                    "ring": ring.value,
                    "label": ring.label,
                    "state": st.value,
                    "is_hitl_gate": ring.is_hitl_gate,
                    "hitl_required": route.hitl_required,
                }
            )

        return {
            "task_id": state.task_id,
            "total_rings": 10,
            "current_ring_no": state.current_ring_no,
            "current_ring": state.ring.value,
            "degree": state.degree.value,
            "complete_percent": round((state.current_ring_no - 1) / 10.0 * 100, 1),
            "rings": rings,
        }

    # ============================================================
    # 推进当前环节（advance）
    # ============================================================
    def advance(
        self,
        task_id: str,
        biz_req_no: str,
        accept: bool = True,
        reject_reason: Optional[str] = None,
        artifact_uri: Optional[str] = None,
        gate_rule: str = "internal_acceptance",
    ) -> FsmState:
        """推进当前环节。

        - 幂等键 `biz_req_no`：同一请求号重复调用时，返回已记录的推进结果（去重）。
        - `accept=True` ：当前环节验收通过 → 进入下一环节。
        - `accept=False`：当前环节验收被拒 → 状态置 FALLBACK（并压入回退栈供回退）。

        Raises:
            BizException: 任务不存在 / 幂等冲突 / 已完结。
        """
        state = self.get_task(task_id)

        # ---- 幂等去重：同 biz_req_no 已推进 ----
        if state.biz_req_no and state.biz_req_no == biz_req_no:
            # 已处理过该请求：直接返回当前状态（不重复推进）。
            return state

        # ---- 完结保护 ----
        if state.current_ring_no >= 10 and state.phase_state == PhaseState.PASSED:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "任务已完结，禁止推进")

        ring = RING_NO_TO_TYPE[state.current_ring_no]
        route: DegreeRoute = get_degree_route(state.degree, ring)

        # ---- 验收看门 ----
        gate = AcceptanceGate(
            task_id=task_id,
            ring_no=state.current_ring_no,
            accepted=bool(accept),
            reject_reason=None if accept else (reject_reason or "验收未通过"),
            gate_rule=gate_rule,
        )

        if accept:
            # 通过：记录主产物 → 压入回退快照 → 前驱指针 → 进入下一环节
            if artifact_uri:
                state.artifacts[str(state.current_ring_no)] = artifact_uri

            # 压入回退栈（快照的是"推进前的旧状态"，前驱指针 = 当前环节）
            snapshot = state.clone()
            snapshot.current_ring_no = state.current_ring_no  # 前驱指针即当前环节
            entry = RollbackEntry(
                prev_ring=ring,
                phase_state=PhaseState.PASSED,
                snapshot=snapshot.snapshot_json(),
            )
            state.rollback_stack.append(entry)

            state.prev_ring_no = state.current_ring_no
            state.phase_state = PhaseState.PASSED
            state.biz_req_no = biz_req_no

            # ---- HITL 敏感环节：推进到下一环节前置 IN_PROGRESS（等待人工/下一执行）----
            if state.current_ring_no < 10:
                state.current_ring_no += 1
                next_route = get_degree_route(state.degree, RING_NO_TO_TYPE[state.current_ring_no])
                state.phase_state = (
                    PhaseState.IN_PROGRESS if next_route.hitl_required else PhaseState.NOT_STARTED
                )
                state.hitl_confirmed = not next_route.hitl_required  # 非 HITL 环节视为已确认
        else:
            # 拒绝：置 FALLBACK，不推进。
            state.phase_state = PhaseState.FALLBACK
            state.biz_req_no = biz_req_no

        self._repo.persist_transition(state, gate)
        return state

    # ============================================================
    # 回退（rollback）
    # ============================================================
    def rollback(self, task_id: str, target_ring_no: int) -> FsmState:
        """回退到目标环节。

        目标环节需小于当前环节号；通过回退栈逐层弹出，找到可恢复的快照。

        Raises:
            BizException: 任务不存在 / 目标环节非法 / 无可用回退快照。
        """
        state = self.get_task(task_id)

        if target_ring_no < 1 or target_ring_no > 10:
            raise BizException(ErrorCode.INVALID_PARAM, "目标环节号非法")
        if target_ring_no >= state.current_ring_no:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                f"目标环节需小于当前环节 {state.current_ring_no}",
            )

        # 从回退栈弹出（栈顶是最近推进快照）
        recovered: Optional[FsmState] = None
        while state.rollback_stack:
            entry = state.rollback_stack.pop()
            snapshot_state = FsmState.decode_snapshot(entry.snapshot)
            if snapshot_state.current_ring_no <= target_ring_no:
                recovered = snapshot_state
                # 回退到目标环节后，丢弃更"新"的快照（已弹出）
                break

        if recovered is None:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "无可用的回退快照")

        # 用恢复的快照覆盖当前状态，但保留时序字段
        restored = recovered.clone()
        restored.task_id = state.task_id
        restored.degree = state.degree
        restored.title = state.title
        restored.subject_field = state.subject_field
        restored.template_id = state.template_id
        restored.biz_req_no = ""  # 回退后清空幂等键，允许重新推进

        # 若回退到的环节是 HITL 敏感，重新置为等待人工
        ring = RING_NO_TO_TYPE[restored.current_ring_no]
        route = get_degree_route(restored.degree, ring)
        restored.phase_state = (
            PhaseState.IN_PROGRESS if route.hitl_required else PhaseState.NOT_STARTED
        )
        restored.hitl_confirmed = not route.hitl_required
        restored.prev_ring_no = (
            restored.current_ring_no - 1 if restored.current_ring_no > 1 else None
        )

        self._repo.persist_transition(restored)
        return restored

    # ============================================================
    # HITL 人工确认（M3 网关预留接口，本期仅落状态不调用外部网关）
    # ============================================================
    def confirm_hitl(
        self,
        task_id: str,
        confirmed: bool = True,
        reject_reason: Optional[str] = None,
    ) -> FsmState:
        """人工确认当前 HITL 敏感环节（环2/4/8/10）。

        本轮仅预留接口与状态落库，真正的 M3 网关逻辑在下一期实现。
        - confirmed=True : 人工通过 → 触发 advance（accept=True）。
        - confirmed=False: 人工拒绝 → 触发 advance（accept=False）。

        Returns:
            更新后的 FSM 状态。
        """
        state = self.get_task(task_id)
        ring = RING_NO_TO_TYPE[state.current_ring_no]
        if not ring.is_hitl_gate:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "当前环节非 HITL 敏感环节")

        return self.advance(
            task_id=task_id,
            biz_req_no=f"HITL-{task_id}-{state.current_ring_no}-{uuid.uuid4().hex[:8]}",
            accept=confirmed,
            reject_reason=reject_reason,
            gate_rule="hitl_gate",
        )


# ---- 说明：FsmState.decode_snapshot 已定义在 fsm/state/models.py ----

