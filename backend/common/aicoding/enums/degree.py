# -*- coding: utf-8 -*-
"""学位层次枚举。"""
from __future__ import annotations

from enum import Enum


class Degree(str, Enum):
    """学位层次。

    - BACHELOR  本科（学士）
    - MASTER    硕士
    - PHD       博士
    """

    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    PHD = "PHD"

    @property
    def label(self) -> str:
        """中文可读标签。"""
        return {
            Degree.BACHELOR: "本科",
            Degree.MASTER: "硕士",
            Degree.PHD: "博士",
        }[self]

    @property
    def min_word_requirement(self) -> int:
        """各学位最低正文字数要求（简化基线，供 guardrail / 大纲校验预留）。"""
        return {
            Degree.BACHELOR: 10000,
            Degree.MASTER: 30000,
            Degree.PHD: 60000,
        }[self]
