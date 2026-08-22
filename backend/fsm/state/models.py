# -*- coding: utf-8 -*-
"""M4 状态存储 —— FSM 领域模型。

本模块定义了 FSM 编排器赖以运转的**纯领域对象**（dataclass），
与数据库 ORM 解耦，便于单元测试在内存中直接构造与推进。

领域对象：
    - AcceptanceGate  布尔化验收看门（每环节 return 必过/回退）
    - FsmState        FSM 运行时状态（当前环节/学位/回退栈/阶段态）
    - DegreeRoute     学位等级路由参数（本科/硕士/博士差异）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from common.aicoding.enums import Degree, PhaseState, RingType


def _now_utc() -> datetime:
    """UTC 当前时间（无时区 naive，便于入库与序列化）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# 学位等级路由参数表（DegreeRoute）
# ============================================================
#: 环1选题创新要求分级（integer 档位，供 guardrail / M2 执行器参考）
class InnovationLevel(str, Enum):
    LOW = "LOW"        # 低档：概述已有结论即可
    MEDIUM = "MEDIUM"  # 中档：需结合新数据/场景做对比分析
    HIGH = "HIGH"      # 高档：需提出方法/理论层面的原创增量


@dataclass(frozen=True)
class DegreeRoute:
    """学位等级路由参数。

    描述某**学位等级**在某**环节**上的差异配置。

    Attributes:
        ring: 所属环节。
        innovation_level: 创新要求档位（环1 选题差异化体现）。
        citation_depth: 引用深度（文献篇数下限，环4 综述差异化体现）。
        outline_depth: 大纲章节深度（最大章节层数，环5 大纲差异化体现）。
        required_outline_levels: 大纲最小层级数。
        hitl_required: 是否 HITL 敏感环节（环2/4/8/10 固定为 True，M3 网关预留）。
        min_word_requirement: 该环节产物最小字数（正文字数基线）。
    """

    ring: RingType
    innovation_level: InnovationLevel
    citation_depth: int
    outline_depth: int
    required_outline_levels: int
    hitl_required: bool
    min_word_requirement: int

    @property
    def key(self) -> str:
        """路由键：`{degree}:{ring}`。"""
        # 由外部调用方提供 degree，本处返回 ring 的规范名。
        return self.ring.value


#: 学位 × 环节 → 路由参数表（本期聚焦环1/4/5 的差异化，其余环节给统一基线）。
#: 键为 (Degree, RingType)，值为 DegreeRoute。
def _build_degree_route_table() -> dict[tuple[Degree, RingType], DegreeRoute]:
    table: dict[tuple[Degree, RingType], DegreeRoute] = {}

    # ---- 环1 选题：创新要求差异 ----
    table[(Degree.BACHELOR, RingType.RING_1)] = DegreeRoute(
        ring=RingType.RING_1, innovation_level=InnovationLevel.LOW,
        citation_depth=0, outline_depth=1, required_outline_levels=1,
        hitl_required=False, min_word_requirement=500,
    )
    table[(Degree.MASTER, RingType.RING_1)] = DegreeRoute(
        ring=RingType.RING_1, innovation_level=InnovationLevel.MEDIUM,
        citation_depth=0, outline_depth=1, required_outline_levels=1,
        hitl_required=False, min_word_requirement=1000,
    )
    table[(Degree.PHD, RingType.RING_1)] = DegreeRoute(
        ring=RingType.RING_1, innovation_level=InnovationLevel.HIGH,
        citation_depth=0, outline_depth=1, required_outline_levels=1,
        hitl_required=False, min_word_requirement=2000,
    )

    # ---- 环2 开题评审（HITL 敏感）----
    for deg in Degree:
        table[(deg, RingType.RING_2)] = DegreeRoute(
            ring=RingType.RING_2, innovation_level=InnovationLevel.MEDIUM,
            citation_depth=10, outline_depth=2, required_outline_levels=2,
            hitl_required=True, min_word_requirement=3000,
        )

    # ---- 环3 文献综述：基础 ----
    for deg in Degree:
        table[(deg, RingType.RING_3)] = DegreeRoute(
            ring=RingType.RING_3, innovation_level=InnovationLevel.LOW,
            citation_depth=0, outline_depth=2, required_outline_levels=2,
            hitl_required=False, min_word_requirement=2000,
        )

    # ---- 环4 综述评审（HITL）：引用深度差异 ----
    table[(Degree.BACHELOR, RingType.RING_4)] = DegreeRoute(
        ring=RingType.RING_4, innovation_level=InnovationLevel.LOW,
        citation_depth=20, outline_depth=2, required_outline_levels=2,
        hitl_required=True, min_word_requirement=8000,
    )
    table[(Degree.MASTER, RingType.RING_4)] = DegreeRoute(
        ring=RingType.RING_4, innovation_level=InnovationLevel.MEDIUM,
        citation_depth=40, outline_depth=2, required_outline_levels=2,
        hitl_required=True, min_word_requirement=12000,
    )
    table[(Degree.PHD, RingType.RING_4)] = DegreeRoute(
        ring=RingType.RING_4, innovation_level=InnovationLevel.HIGH,
        citation_depth=80, outline_depth=2, required_outline_levels=2,
        hitl_required=True, min_word_requirement=20000,
    )

    # ---- 环5 大纲生成：章节深度差异 ----
    table[(Degree.BACHELOR, RingType.RING_5)] = DegreeRoute(
        ring=RingType.RING_5, innovation_level=InnovationLevel.LOW,
        citation_depth=0, outline_depth=2, required_outline_levels=2,
        hitl_required=False, min_word_requirement=10000,
    )
    table[(Degree.MASTER, RingType.RING_5)] = DegreeRoute(
        ring=RingType.RING_5, innovation_level=InnovationLevel.MEDIUM,
        citation_depth=0, outline_depth=3, required_outline_levels=3,
        hitl_required=False, min_word_requirement=30000,
    )
    table[(Degree.PHD, RingType.RING_5)] = DegreeRoute(
        ring=RingType.RING_5, innovation_level=InnovationLevel.HIGH,
        citation_depth=0, outline_depth=4, required_outline_levels=4,
        hitl_required=False, min_word_requirement=60000,
    )

    # ---- 环6 初稿撰写 ----
    for deg in Degree:
        table[(deg, RingType.RING_6)] = DegreeRoute(
            ring=RingType.RING_6, innovation_level=InnovationLevel.MEDIUM,
            citation_depth=0, outline_depth=3, required_outline_levels=3,
            hitl_required=False, min_word_requirement=deg.min_word_requirement,
        )

    # ---- 环7 万方查重（M7 预留）----
    for deg in Degree:
        table[(deg, RingType.RING_7)] = DegreeRoute(
            ring=RingType.RING_7, innovation_level=InnovationLevel.MEDIUM,
            citation_depth=0, outline_depth=3, required_outline_levels=3,
            hitl_required=False, min_word_requirement=deg.min_word_requirement,
        )

    # ---- 环8 合规校验（HITL 敏感）----
    for deg in Degree:
        table[(deg, RingType.RING_8)] = DegreeRoute(
            ring=RingType.RING_8, innovation_level=InnovationLevel.MEDIUM,
            citation_depth=0, outline_depth=3, required_outline_levels=3,
            hitl_required=True, min_word_requirement=deg.min_word_requirement,
        )

    # ---- 环9 定稿排版 ----
    for deg in Degree:
        table[(deg, RingType.RING_9)] = DegreeRoute(
            ring=RingType.RING_9, innovation_level=InnovationLevel.MEDIUM,
            citation_depth=0, outline_depth=3, required_outline_levels=3,
            hitl_required=False, min_word_requirement=deg.min_word_requirement,
        )

    # ---- 环10 终稿交付（HITL 敏感）----
    for deg in Degree:
        table[(deg, RingType.RING_10)] = DegreeRoute(
            ring=RingType.RING_10, innovation_level=InnovationLevel.HIGH,
            citation_depth=0, outline_depth=3, required_outline_levels=3,
            hitl_required=True, min_word_requirement=deg.min_word_requirement,
        )

    return table


#: 全局学位路由参数表。
DEGREE_ROUTE_TABLE: dict[tuple[Degree, RingType], DegreeRoute] = _build_degree_route_table()


def get_degree_route(degree: Degree, ring: RingType) -> DegreeRoute:
    """按 (学位, 环节) 获取路由参数；未配置则回退到同环节首个学位基线。

    Raises:
        ValueError: 若该环节完全未在路由表中登记。
    """
    key = (degree, ring)
    if key in DEGREE_ROUTE_TABLE:
        return DEGREE_ROUTE_TABLE[key]
    # 回退：取任意该环节登记（默认 BACHELOR 基线）
    for deg in Degree:
        if (deg, ring) in DEGREE_ROUTE_TABLE:
            return DEGREE_ROUTE_TABLE[(deg, ring)]
    raise ValueError(f"未登记路由参数的环节: {ring}")


# ============================================================
# 回退栈元素（前驱指针 + JSON 快照）
# ============================================================
@dataclass
class RollbackEntry:
    """回退栈元素。

    对应系统设计 §3.2.M1 的“前驱指针 + JSON 快照”：

    Attributes:
        prev_ring: 被快照的**前一环节**编号（前驱指针）。
        phase_state: 快照时的阶段态。
        snapshot: JSON 序列化的运行时快照（产物指针、验收信息等）。
        created_at: 快照时间。
    """

    prev_ring: RingType
    phase_state: PhaseState
    snapshot: str
    created_at: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_ring": self.prev_ring.value,
            "phase_state": self.phase_state.value,
            "snapshot": self.snapshot,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RollbackEntry":
        return cls(
            prev_ring=RingType(data["prev_ring"]),
            phase_state=PhaseState(data["phase_state"]),
            snapshot=data.get("snapshot", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================
# FsmState —— FSM 运行时状态
# ============================================================
@dataclass
class FsmState:
    """FSM 运行时状态。

    Attributes:
        task_id: 任务 ID。
        current_ring_no: 当前环节号（1~10，对应 RING_1..RING_10）。
        degree: 学位等级。
        prev_ring_no: 前驱环节号（None 表示首个环节）。
        rollback_stack: 回退栈（最近快照在末尾）。
        phase_state: 当前环节的阶段态。
        title: 论文题目。
        subject_field: 学科方向。
        template_id: 论文模板 ID。
        hitl_confirmed: 当前 HITL 环节是否已人工确认（M3 网关预留）。
        artifacts: 主产物指针（{ring_no: artifact_uri}，同步）。
        aux_artifacts: 附属产物指针（{ring_no: [artifact_uri]}，异步预留）。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    task_id: str
    current_ring_no: int
    degree: Degree
    prev_ring_no: Optional[int] = None
    rollback_stack: list[RollbackEntry] = field(default_factory=list)
    phase_state: PhaseState = PhaseState.NOT_STARTED
    title: str = ""
    subject_field: str = ""
    template_id: str = ""
    hitl_confirmed: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)
    aux_artifacts: dict[str, list[str]] = field(default_factory=dict)
    biz_req_no: str = ""  # 幂等键（推进操作的唯一请求号）
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)

    # ---- 便捷谓词 ----
    @property
    def ring(self) -> RingType:
        """当前环节类型。"""
        return RingType(f"RING_{self.current_ring_no}")

    @property
    def current_route(self) -> DegreeRoute:
        """当前环节的学位路由参数。"""
        return get_degree_route(self.degree, self.ring)

    @property
    def is_finished(self) -> bool:
        """是否已走完十环节（当前环节 = 10 且 PASSED）。"""
        return self.current_ring_no == 10 and self.phase_state == PhaseState.PASSED

    def clone(self) -> "FsmState":
        """深拷贝（用于回退栈快照与并发防护）。"""
        import copy

        return copy.deepcopy(self)

    def snapshot_json(self) -> str:
        """把当前状态序列化为 JSON 快照（不含回退栈自身防递归）。"""
        payload = {
            "task_id": self.task_id,
            "current_ring_no": self.current_ring_no,
            "degree": self.degree.value,
            "prev_ring_no": self.prev_ring_no,
            "phase_state": self.phase_state.value,
            "title": self.title,
            "subject_field": self.subject_field,
            "template_id": self.template_id,
            "hitl_confirmed": self.hitl_confirmed,
            "artifacts": self.artifacts,
            "aux_artifacts": self.aux_artifacts,
            "biz_req_no": self.biz_req_no,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def restore_from_snapshot(self, snapshot: str) -> None:
        """从 JSON 快照恢复（用于回退动作）。"""
        payload = json.loads(snapshot)
        self.task_id = payload["task_id"]
        self.current_ring_no = payload["current_ring_no"]
        self.degree = Degree(payload["degree"])
        self.prev_ring_no = payload.get("prev_ring_no")
        self.phase_state = PhaseState(payload["phase_state"])
        self.title = payload.get("title", "")
        self.subject_field = payload.get("subject_field", "")
        self.template_id = payload.get("template_id", "")
        self.hitl_confirmed = payload.get("hitl_confirmed", False)
        self.artifacts = payload.get("artifacts", {})
        self.aux_artifacts = payload.get("aux_artifacts", {})
        self.biz_req_no = payload.get("biz_req_no", "")
        self.updated_at = _now_utc()

    @classmethod
    def decode_snapshot(cls, snapshot: str) -> "FsmState":
        """从 JSON 快照还原一个全新的 FsmState（用于回退栈恢复）。"""
        payload = json.loads(snapshot)
        return cls(
            task_id=payload.get("task_id", ""),
            current_ring_no=payload["current_ring_no"],
            degree=Degree(payload["degree"]),
            prev_ring_no=payload.get("prev_ring_no"),
            rollback_stack=[],
            phase_state=PhaseState(payload["phase_state"]),
            title=payload.get("title", ""),
            subject_field=payload.get("subject_field", ""),
            template_id=payload.get("template_id", ""),
            hitl_confirmed=payload.get("hitl_confirmed", False),
            artifacts=payload.get("artifacts", {}),
            aux_artifacts=payload.get("aux_artifacts", {}),
            biz_req_no=payload.get("biz_req_no", ""),
        )


# ============================================================
# AcceptanceGate —— 布尔化验收看门
# ============================================================
@dataclass
class AcceptanceGate:
    """布尔化验收看门。

    每次环节推进都必须返回布尔化的 accept 结果：
        - accepted=True : 允许进入下一环节
        - accepted=False: 触发回退/拒绝（阶段态置 FALLBACK）

    Attributes:
        task_id: 任务 ID。
        ring_no: 看门所属环节号。
        accepted: 是否通过。
        reject_reason: 驳回原因（accepted=False 时必填）。
        gate_rule: 触发看门的规则名（如 "citation_depth"、"internal_acceptance"）。
        checked_at: 看门检查时间。
    """

    task_id: str
    ring_no: int
    accepted: bool
    reject_reason: Optional[str] = None
    gate_rule: str = "internal_acceptance"
    checked_at: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ring_no": self.ring_no,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
            "gate_rule": self.gate_rule,
            "checked_at": self.checked_at.isoformat(),
        }
