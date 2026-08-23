# -*- coding: utf-8 -*-
"""M1 FSM 编排器 —— FsmOrchestrator。

职责（对齐系统设计 §3.2.M1.2）：
    1. 维护十环节状态机（RingType.RING_1..RING_10）。
    2. 学位等级路由：本科/硕士/博士在环节阈值、创新要求、引用深度上的差异，
       通过 DegreeRoute 参数表体现（fsm/state/models.py 的 DEGREE_ROUTE_TABLE）。
    3. 回退栈：前驱指针 + JSON 快照（RollbackEntry）。
    4. 验收看门：每环节 return 布尔化 accept（AcceptanceGate）。

事务边界：状态推进/回退均通过 repository.persist_transition（FSM + Gate 同事务）。

确认说明：所有环节都遵守“执行产物 → 自动验收 → 用户确认 → 推进”的协议；
环2/4/8/10 额外标记为 HITL 敏感环节，供界面和后续审批策略使用。
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

        completed_rings = state.current_ring_no - 1
        if state.is_finished:
            completed_rings = 10

        return {
            "task_id": state.task_id,
            "total_rings": 10,
            "current_ring_no": state.current_ring_no,
            "current_ring": state.ring.value,
            "degree": state.degree.value,
            "complete_percent": round(completed_rings / 10.0 * 100, 1),
            "phase_state": state.phase_state.value,
            "has_artifact": str(state.current_ring_no) in state.artifacts,
            "can_execute": state.phase_state in (
                PhaseState.NOT_STARTED,
                PhaseState.IN_PROGRESS,
                PhaseState.FALLBACK,
            ),
            "can_confirm": state.phase_state == PhaseState.WAITING_APPROVAL,
            "rings": rings,
        }

    # ============================================================
    # 提交执行产物（不推进）
    # ============================================================
    def submit_execution(
        self,
        task_id: str,
        artifact_uri: str,
        accepted: bool = True,
    ) -> FsmState:
        """记录当前环节执行结果，等待用户确认后再推进。

        执行体只能把当前环节置为 ``WAITING_APPROVAL``；只有
        :meth:`advance` 或 :meth:`confirm_hitl` 才能推进。失败产物仍保留，
        供界面解释失败原因和执行回退。
        """
        state = self.get_task(task_id)
        if state.is_finished:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "任务已完结，禁止再次执行")
        if state.phase_state == PhaseState.PASSED:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "当前环节已经通过")
        if not artifact_uri:
            raise BizException(ErrorCode.INVALID_PARAM, "执行产物不能为空")

        state.artifacts[str(state.current_ring_no)] = artifact_uri
        state.phase_state = (
            PhaseState.WAITING_APPROVAL if accepted else PhaseState.FALLBACK
        )
        state.hitl_confirmed = False
        state.biz_req_no = ""
        self._repo.persist_transition(state)
        return state

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
        artifact_event: Optional[dict[str, Any]] = None,
    ) -> FsmState:
        """推进当前环节。

        - 幂等键 `biz_req_no`：同一请求号重复调用时，返回已记录的推进结果（去重）。
        - 当前环节必须已经执行并处于 ``WAITING_APPROVAL``。
        - `accept=True` ：用户确认当前产物 → 进入下一环节。
        - `accept=False`：用户拒绝当前产物 → 状态置 FALLBACK。

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

        if state.phase_state != PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                "当前环节尚未执行或没有待确认产物，禁止推进",
            )
        if str(state.current_ring_no) not in state.artifacts:
            raise BizException(ErrorCode.FSM_INVALID_TRANSITION, "当前环节产物缺失，禁止推进")

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

        if artifact_event is not None:
            self._append_artifact_event(
                state,
                artifact_event,
                approved=bool(accept),
                reject_reason=reject_reason or "",
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
            state.hitl_confirmed = ring.is_hitl_gate

            # 下一环必须重新执行。HITL 表示产物生成后的人工验收，不是执行前确认。
            if state.current_ring_no < 10:
                state.current_ring_no += 1
                state.phase_state = PhaseState.NOT_STARTED
                state.hitl_confirmed = False
        else:
            # 拒绝：置 FALLBACK，不推进。
            state.phase_state = PhaseState.FALLBACK
            state.biz_req_no = biz_req_no

        self._repo.persist_transition(state, gate)
        return state

    @staticmethod
    def _append_artifact_event(
        state: FsmState,
        event: dict[str, Any],
        *,
        approved: bool,
        reject_reason: str,
    ) -> None:
        """把产物审批事件写入 FSM 事务 Outbox。

        Outbox 与 FSM/Gate 由 ``persist_transition`` 原子提交；产物仓库随后幂等投影。
        """
        if not isinstance(event, dict):
            raise BizException(ErrorCode.INVALID_PARAM, "artifact_event 必须是对象")
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            event_id = f"EVT-{uuid.uuid4().hex[:20].upper()}"
        task_id = str(event.get("task_id", state.task_id))
        stage_no = int(event.get("stage_no", state.current_ring_no) or 0)
        if task_id != state.task_id or stage_no != state.current_ring_no:
            raise BizException(ErrorCode.INVALID_PARAM, "产物事件与当前任务/环节不一致")

        outbox = state.aux_artifacts.setdefault("artifact_outbox", [])
        if not isinstance(outbox, list):
            raise BizException(ErrorCode.TASK_STATE_INVALID, "artifact_outbox 状态损坏")
        if any(str(item.get("event_id", "")) == event_id for item in outbox if isinstance(item, dict)):
            return

        normalized = dict(event)
        normalized.update(
            {
                "event_id": event_id,
                "task_id": state.task_id,
                "stage_no": state.current_ring_no,
                "approved": approved,
                "reason": reject_reason or str(event.get("reason", "")),
                "projection_status": "PENDING",
            }
        )
        outbox.append(normalized)

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
        # Outbox 是不可丢失的审批审计流，不属于可回退的业务内容快照。
        current_outbox = state.clone().aux_artifacts.get("artifact_outbox", [])

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
        restored.aux_artifacts["artifact_outbox"] = current_outbox

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
    # HITL 敏感环节确认（兼容低层 API；工作台统一使用 confirm_ring）
    # ============================================================
    def delete_task(self, task_id: str) -> None:
        """删除任务（仓储移除；回退栈/看门一并清理）。"""
        state = self.get_task(task_id)  # 不存在抛 TASK_NOT_FOUND
        # 仓储提供 delete 则清理（InMemory 与 SqlAlchemy 均实现）
        if hasattr(self._repo, "delete"):
            self._repo.delete(task_id)

    def mark_artifact_event_projected(
        self,
        task_id: str,
        event_id: str,
        artifact_id: str,
    ) -> FsmState:
        """确认 Outbox 事件已被幂等投影到产物仓库。"""
        state = self.get_task(task_id)
        outbox = state.aux_artifacts.get("artifact_outbox", [])
        if not isinstance(outbox, list):
            raise BizException(ErrorCode.TASK_STATE_INVALID, "artifact_outbox 状态损坏")
        matched = False
        for event in outbox:
            if not isinstance(event, dict) or str(event.get("event_id", "")) != event_id:
                continue
            matched = True
            if event.get("projection_status") == "PROJECTED":
                return state
            event["projection_status"] = "PROJECTED"
            event["artifact_id"] = artifact_id
            break
        if not matched:
            raise BizException(ErrorCode.INVALID_PARAM, f"Outbox 事件不存在: {event_id}")
        self._repo.persist_transition(state)
        return state

    def confirm_hitl(
        self,
        task_id: str,
        confirmed: bool = True,
        reject_reason: Optional[str] = None,
    ) -> FsmState:
        """人工确认当前 HITL 敏感环节（环2/4/8/10）。

        该接口只保留给低层 FSM API；工作台十环流程统一调用应用层
        ``confirm_ring``，从而确保普通环节也不能绕过人工确认。
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
            gate_rule="hitl_confirmation",
        )


# ---- 说明：FsmState.decode_snapshot 已定义在 fsm/state/models.py ----

