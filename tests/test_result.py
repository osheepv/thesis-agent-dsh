# -*- coding: utf-8 -*-
"""Result 统一响应包装单元测试。"""
from __future__ import annotations

from common.aicoding.dto import Result


def test_ok_default():
    r = Result.ok(data={"a": 1})
    assert r.code == 0
    assert r.msg == "ok"
    assert r.data == {"a": 1}
    assert r.is_ok is True
    assert r.tenantId == "default"


def test_ok_with_trace():
    r = Result.ok(data="hello", trace_id="trace-1", tenant_id="tenant-2")
    assert r.traceId == "trace-1"
    assert r.tenantId == "tenant-2"
    assert r.is_ok is True


def test_fail():
    r = Result.fail(code=100001, msg="任务不存在")
    assert r.code == 100001
    assert r.msg == "任务不存在"
    assert r.is_ok is False
    assert r.data is None


def test_generic_type_holds_list():
    r = Result.ok(data=[1, 2, 3])
    assert r.data == [1, 2, 3]


def test_serialize_dict():
    r = Result.ok(data={"k": "v"}, trace_id="t")
    d = r.model_dump()
    assert d["code"] == 0
    assert d["traceId"] == "t"
