# -*- coding: utf-8 -*-
"""业务错误码定义（6 位数字码）。

编码约定（前 2 位业务域 + 后 4 位明细）：
    00xxxx  通用/系统级
    10xxxx  任务域
    20xxxx  环节执行域（M2）
    30xxxx  FSM 编排域（M1）
    40xxxx  状态存储域（M4）
    50xxxx  docx 模板解析/生成校验（M5/M6）
    60xxxx  M7 万方查重（预留）
    70xxxx  M8 Guardrail（预留）
    80xxxx  M9 知识库（预留）
"""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """6 位业务错误码。"""

    # ---------- 通用/系统级 00xxxx ----------
    OK = "000000"
    UNKNOWN_ERROR = "000001"
    INVALID_PARAM = "000002"
    UNAUTHORIZED = "000003"
    FORBIDDEN = "000004"
    NOT_FOUND = "000005"
    SYSTEM_ERROR = "000006"
    TIMEOUT = "000007"
    RATE_LIMITED = "000008"

    # ---------- 任务域 10xxxx ----------
    TASK_NOT_FOUND = "100001"
    TASK_STATE_INVALID = "100002"
    TASK_ALREADY_EXISTS = "100003"
    TEMPLATE_NOT_FOUND = "100004"

    # ---------- 环节执行域（M2）20xxxx ----------
    RING_NOT_IMPLEMENTED = "200001"
    RING_EXECUTION_FAILED = "200002"
    RING_RETRY_EXHAUSTED = "200003"
    RING_OUTPUT_INVALID = "200004"

    # ---------- FSM 编排域（M1）30xxxx ----------
    FSM_INVALID_TRANSITION = "300001"
    FSM_CURRENT_RING_GUARD = "300002"
    FSM_ACCEPTANCE_REJECTED = "300003"

    # ---------- 状态存储域（M4）40xxxx ----------
    STATE_WRITE_FAILED = "400001"
    STATE_READ_FAILED = "400002"
    STATE_CONFLICT = "400003"

    # ---------- docx 模板解析/生成校验（M5/M6）50xxxx ----------
    DOCX_PARSE_FAILED = "500001"
    DOCX_TEMPLATE_INVALID = "500002"
    DOCX_GENERATE_FAILED = "500003"
    DOCX_VALIDATE_FAILED = "500004"

    # ---------- M7 万方查重（预留）60xxxx ----------
    WANFANG_API_ERROR = "600001"
    WANFANG_TIMEOUT = "600002"

    # ---------- M8 Guardrail（预留）70xxxx ----------
    GUARDRAIL_POLICY_VIOLATED = "700001"
    GUARDRAIL_FACTUAL_VIOLATED = "700002"

    # ---------- M9 知识库（预留）80xxxx ----------
    KB_SESSION_NOT_BOUND = "800001"
    KB_TOPIC_ISOLATION_VIOLATED = "800002"

    @property
    def default_msg(self) -> str:
        """错误码默认读信息。"""
        return _ERROR_CODE_DEFAULT_MSG.get(self, "业务处理失败")


_ERROR_CODE_DEFAULT_MSG: dict[ErrorCode, str] = {
    ErrorCode.OK: "成功",
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.INVALID_PARAM: "参数不合法",
    ErrorCode.UNAUTHORIZED: "未认证",
    ErrorCode.FORBIDDEN: "无权限",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.SYSTEM_ERROR: "系统异常",
    ErrorCode.TIMEOUT: "请求超时",
    ErrorCode.RATE_LIMITED: "触发限流",
    ErrorCode.TASK_NOT_FOUND: "任务不存在",
    ErrorCode.TASK_STATE_INVALID: "任务状态非法",
    ErrorCode.TASK_ALREADY_EXISTS: "任务已存在",
    ErrorCode.TEMPLATE_NOT_FOUND: "论文模板不存在",
    ErrorCode.RING_NOT_IMPLEMENTED: "环节未实现",
    ErrorCode.RING_EXECUTION_FAILED: "环节执行失败",
    ErrorCode.RING_RETRY_EXHAUSTED: "环节重试次数耗尽",
    ErrorCode.RING_OUTPUT_INVALID: "环节输出不合法",
    ErrorCode.FSM_INVALID_TRANSITION: "FSM 非法流转",
    ErrorCode.FSM_CURRENT_RING_GUARD: "FSM 当前环节校验失败",
    ErrorCode.FSM_ACCEPTANCE_REJECTED: "验收被拒绝",
    ErrorCode.STATE_WRITE_FAILED: "状态写入失败",
    ErrorCode.STATE_READ_FAILED: "状态读取失败",
    ErrorCode.STATE_CONFLICT: "状态并发冲突",
    ErrorCode.DOCX_PARSE_FAILED: "docx 解析失败",
    ErrorCode.DOCX_TEMPLATE_INVALID: "docx 模板非法",
    ErrorCode.DOCX_GENERATE_FAILED: "docx 生成失败",
    ErrorCode.DOCX_VALIDATE_FAILED: "docx 校验失败",
    ErrorCode.WANFANG_API_ERROR: "万方接口异常",
    ErrorCode.WANFANG_TIMEOUT: "万方接口超时",
    ErrorCode.GUARDRAIL_POLICY_VIOLATED: "违反政策红线",
    ErrorCode.GUARDRAIL_FACTUAL_VIOLATED: "事实性校验未通过",
    ErrorCode.KB_SESSION_NOT_BOUND: "会话未绑定知识库",
    ErrorCode.KB_TOPIC_ISOLATION_VIOLATED: "违反会话知识隔离",
}
