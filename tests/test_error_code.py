# -*- coding: utf-8 -*-
"""ErrorCode + BizException 单元测试。"""
from __future__ import annotations

from common.aicoding.exception import BizException, ErrorCode


def test_error_code_is_six_digit():
    for ec in ErrorCode:
        assert len(ec.value) == 6, f"{ec} 非 6 位错误码"
        assert ec.value.isdigit()


def test_error_code_unique():
    values = [ec.value for ec in ErrorCode]
    assert len(values) == len(set(values)), "错误码重复"


def test_error_code_domains():
    assert ErrorCode.TASK_NOT_FOUND.value == "100001"
    assert ErrorCode.RING_NOT_IMPLEMENTED.value == "200001"
    assert ErrorCode.FSM_INVALID_TRANSITION.value == "300001"
    assert ErrorCode.STATE_WRITE_FAILED.value == "400001"
    assert ErrorCode.DOCX_PARSE_FAILED.value == "500001"
    assert ErrorCode.WANFANG_API_ERROR.value == "600001"
    assert ErrorCode.GUARDRAIL_POLICY_VIOLATED.value == "700001"
    assert ErrorCode.KB_SESSION_NOT_BOUND.value == "800001"


def test_default_msg():
    assert ErrorCode.OK.default_msg == "成功"
    assert ErrorCode.TASK_NOT_FOUND.default_msg == "任务不存在"


def test_biz_exception_from_error_code():
    exc = BizException(ErrorCode.TASK_NOT_FOUND)
    assert exc.code == "100001"
    assert exc.msg == "任务不存在"
    assert exc.http_status == 200


def test_biz_exception_custom_msg():
    exc = BizException(ErrorCode.TASK_NOT_FOUND, "自定义错误信息")
    assert exc.msg == "自定义错误信息"


def test_biz_exception_to_dict():
    exc = BizException(ErrorCode.DOCX_PARSE_FAILED)
    d = exc.to_dict()
    assert d["code"] == 500001
    assert d["msg"] == "docx 解析失败"
