# -*- coding: utf-8 -*-
"""FSM 十环节类型枚举（M1 FSM 编排器的环节定义）。"""
from __future__ import annotations

from enum import Enum


class RingType(str, Enum):
    """十环节 FSM 类型。

    编号与系统设计 M1 一致（应用落地层）：
      RING_1  选题           RING_6  初稿撰写
      RING_2  开题评审(HITL)  RING_7  万方查重(M7)
      RING_3  文献综述       RING_8  合规校验(HITL)
      RING_4  综述评审(HITL) RING_9  定稿排版
      RING_5  大纲生成       RING_10 终稿交付(HITL)
    """

    RING_1 = "RING_1"
    RING_2 = "RING_2"
    RING_3 = "RING_3"
    RING_4 = "RING_4"
    RING_5 = "RING_5"
    RING_6 = "RING_6"
    RING_7 = "RING_7"
    RING_8 = "RING_8"
    RING_9 = "RING_9"
    RING_10 = "RING_10"

    @property
    def label(self) -> str:
        """中文可读标签。"""
        return {
            RingType.RING_1: "选题",
            RingType.RING_2: "开题评审",
            RingType.RING_3: "文献综述",
            RingType.RING_4: "综述评审",
            RingType.RING_5: "大纲生成",
            RingType.RING_6: "初稿撰写",
            RingType.RING_7: "万方查重",
            RingType.RING_8: "合规校验",
            RingType.RING_9: "定稿排版",
            RingType.RING_10: "终稿交付",
        }[self]

    @property
    def is_hitl_gate(self) -> bool:
        """是否为 HITL 通过式网关环节（固定为环2/4/8/10）。"""
        return self in (RingType.RING_2, RingType.RING_4, RingType.RING_8, RingType.RING_10)


#: 各环节默认超时基线（秒），供 M1 FSM 权限编排与后台任务同步使用。
RING_TYPE_DEFAULT_DURATION: dict[RingType, int] = {
    RingType.RING_1: 300,      # 选题
    RingType.RING_2: 3600,     # 开题评审（HITL，等待人工）
    RingType.RING_3: 1800,     # 文献综述
    RingType.RING_4: 3600,     # 综述评审（HITL）
    RingType.RING_5: 900,      # 大纲生成
    RingType.RING_6: 3600,     # 初稿撰写
    RingType.RING_7: 1800,     # 万方查重（M7，预留）
    RingType.RING_8: 3600,     # 合规校验（HITL）
    RingType.RING_9: 1800,     # 定稿排版
    RingType.RING_10: 3600,    # 终稿交付（HITL）
}
