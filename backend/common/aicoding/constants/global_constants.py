# -*- coding: utf-8 -*-
"""全局常量配置。

包含超时/重试基线、HITL 网关环节定义，以及 M7 万方可信边界三条规则（二期硬编码位）。
"""
from __future__ import annotations

from typing import Final

# ============================================================
# 通用 HTTP / 超时 / 重试 基线
# ============================================================

#: 默认 HTTP 超时（秒）
HTTP_TIMEOUT_DEFAULT: Final[int] = 30
#: 快速操作（健康检查/轻查询）超时（秒）
HTTP_TIMEOUT_FAST: Final[int] = 5
#: 默认重试次数
RETRY_MAX_DEFAULT: Final[int] = 3
#: 重试退避基数（秒），间隔 = base * 2^(attempt)
RETRY_BACKOFF_BASE: Final[float] = 1.0
#: 单环节执行超时基线（秒），兜底值，具体见 RingType·RING_TYPE_DEFAULT_DURATION
RING_EXEC_TIMEOUT_DEFAULT: Final[int] = 3600

# ============================================================
# HITL 通过式网关环节（固定环2/4/8/10，不随二期调整）
# ============================================================

#: HITL 网关环节编号（与 RingType.is_hitl_gate 保持一致）
HITL_GATE_RINGS: Final[list[str]] = ["RING_2", "RING_4", "RING_8", "RING_10"]
#: HITL 缺省审批人（占位，二期接入真实用户体系后替换）
HITL_DEFAULT_APPROVER: Final[str] = "advisor"

# ============================================================
# M7 万方可信边界（二期实现，本期仅硬编码三条规则文案位）
# 说明：以下三条规则为「万方可信边界」，M7 必须严格遵守。
# ============================================================

#: 规则 1：单次检索/单任务引用文献上限 50 篇。
WANFANG_MAX_LIMIT: Final[int] = 50

#: 规则 2：检索「没查到」要区分两种情况——接口异常 vs 确实无结果，文案不可混淆。
WANFANG_MSG_NOT_FOUND: Final[str] = "未检索到相关文献"      # 确实无结果
WANFANG_MSG_API_ERROR: Final[str] = "万方检索服务暂不可用"   # 接口异常

#: 规则 3：学科「无名字」（学科映射缺失/无法命名）必须显式标注，不得静默回退到默认学科。
WANFANG_MSG_DISCIPLINE_NO_NAME: Final[str] = "未能识别该资料所属学科，请人工确认"


#: M7 万方可信边界完整规则描述（供日志/文档引用）。
WANFANG_TRUST_RULES: Final[dict[str, str]] = {
    "max_limit_50": "可信边界一：单任务引用文献上限 50 篇（>=50 截断标注）",
    "not_found_two_cases": "可信边界二：'没查到'必须区分接口异常与确实无结果两种情况",
    "discipline_must_named": "可信边界三：学科无名字时必须显式标注，禁止静默回退默认学科",
}

# ============================================================
# M9 会话知识库隔离（二期实现，本期预留数据结构常量）
# ============================================================

#: 会话知识库隔离：允许为每个 session 建立独立知识库命名空间前缀。
KB_SESSION_NAMESPACE_PREFIX: Final[str] = "kb_session"
#: 单会话知识库最大绑定数（二期）。
KB_MAX_BINDINGS_PER_SESSION: Final[int] = 5
