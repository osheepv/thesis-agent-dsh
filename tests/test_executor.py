# -*- coding: utf-8 -*-
"""M2 环节执行体单元测试。

覆盖：
1. 三个执行体（环1/5/6）的四字段返回（output/accept/fallbackTo/issues/evidence）。
2. 学位差异体现（候选数量、章节数量、每章段落基准数）。
3. HITL 预留环节标志（环2/4/8/10 hitl_required=True）。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree, RingType
from backend.executor import ExecContext, ExecResult, get_executor
from backend.executor.base import EXECUTOR_REGISTRY


# ---------- 环1 选题执行体 ----------
class TestRing1Topic:
    def test_four_field_return(self):
        ctx = ExecContext(subject_field="计算机视觉", degree=Degree.MASTER)
        res = get_executor(1).execute(ctx)
        assert isinstance(res, ExecResult)
        assert isinstance(res.output, str) and res.output
        assert isinstance(res.accept, bool) and res.accept is True
        assert res.fallbackTo is None
        assert isinstance(res.issues, list)
        assert isinstance(res.evidence, dict)
        data = json.loads(res.output)
        assert "candidates" in data
        assert len(data["candidates"]) > 0

    def test_degree_difference_candidate_count(self):
        ctx_b = ExecContext(subject_field="NLP", degree=Degree.BACHELOR)
        ctx_m = ExecContext(subject_field="NLP", degree=Degree.MASTER)
        ctx_p = ExecContext(subject_field="NLP", degree=Degree.PHD)
        n_b = len(json.loads(get_executor(1).execute(ctx_b).output)["candidates"])
        n_m = len(json.loads(get_executor(1).execute(ctx_m).output)["candidates"])
        n_p = len(json.loads(get_executor(1).execute(ctx_p).output)["candidates"])
        assert n_b < n_m < n_p, "候选题目数应随学位层次递增（深者多、浅者少）"

    def test_degree_fit_field_present(self):
        ctx = ExecContext(subject_field="数据挖掘", degree=Degree.BACHELOR)
        data = json.loads(get_executor(1).execute(ctx).output)
        for c in data["candidates"]:
            assert c["degree_fit"]
            assert "本科" in c["degree_fit"]

    def test_missing_subject_field_raises(self):
        ctx = ExecContext(subject_field="", degree=Degree.MASTER)
        with pytest.raises(ValueError):
            get_executor(1).execute(ctx)


# ---------- 环5 大纲生成执行体 ----------
class TestRing5Outline:
    def test_four_field_return(self):
        ctx = ExecContext(subject_field="计算机视觉", degree=Degree.MASTER, theme="基于深度学习的X识别")
        res = get_executor(5).execute(ctx)
        assert isinstance(res, ExecResult)
        assert res.output and res.accept is True and res.fallbackTo is None
        assert isinstance(res.issues, list) and isinstance(res.evidence, dict)
        data = json.loads(res.output)
        assert data["theme"] == "基于深度学习的X识别"
        assert len(data["chapters"]) > 0

    def test_degree_difference_chapter_depth(self):
        ctx_b = ExecContext(subject_field="NLP", degree=Degree.BACHELOR, theme="T")
        ctx_p = ExecContext(subject_field="NLP", degree=Degree.PHD, theme="T")
        n_b = len(json.loads(get_executor(5).execute(ctx_b).output)["chapters"])
        n_p = len(json.loads(get_executor(5).execute(ctx_p).output)["chapters"])
        assert n_b < n_p, "博士章节深度应高于本科（节点更多）"

    def test_outline_has_levels_and_numbers(self):
        ctx = ExecContext(subject_field="推荐系统", degree=Degree.MASTER, theme="T")
        data = json.loads(get_executor(5).execute(ctx).output)
        levels = {ch["level"] for ch in data["chapters"]}
        assert 1 in levels and 2 in levels, "大纲应包含章(level=1)与节(level=2)" 
        assert any(ch["number"].startswith("第") for ch in data["chapters"])


# ---------- 环6 分章撰写执行体 ----------
class TestRing6Chapter:
    def _build_ctx(self, degree: Degree) -> ExecContext:
        ctx = ExecContext(subject_field="计算机视觉", degree=degree, theme="基于深度学习的X识别")
        ctx.outline = get_executor(5).execute(ctx).output
        return ctx

    def test_four_field_return(self):
        res = get_executor(6).execute(self._build_ctx(Degree.MASTER))
        assert isinstance(res, ExecResult)
        assert res.output and res.accept is False and res.fallbackTo == 6
        assert "降级模板稿禁止" in res.issues[0]
        assert isinstance(res.issues, list) and isinstance(res.evidence, dict)
        data = json.loads(res.output)
        assert len(data["chapters"]) > 0
        assert data["chapters"][0]["chapter_title"]
        assert data["chapters"][0]["content"].startswith("## ")

    def test_degree_difference_paragraph_depth(self):
        res_b = get_executor(6).execute(self._build_ctx(Degree.BACHELOR))
        res_p = get_executor(6).execute(self._build_ctx(Degree.PHD))
        db = json.loads(res_b.output)
        dp = json.loads(res_p.output)
        wb = db["total_words"]
        wp = dp["total_words"]
        assert wb < wp, "博士章正文应更深（字数更多）"

    def test_chapter_draft_shape(self):
        data = json.loads(get_executor(6).execute(self._build_ctx(Degree.MASTER)).output)
        ch = data["chapters"][0]
        assert "chapter_no" in ch and "chapter_title" in ch and "content" in ch and "word_count" in ch


# ---------- 注册表 & HITL 预留环节 ----------
class TestRegistryAndHitl:
    def test_executors_registered(self):
        assert RingType.RING_1 in EXECUTOR_REGISTRY
        assert RingType.RING_5 in EXECUTOR_REGISTRY
        assert RingType.RING_6 in EXECUTOR_REGISTRY

    def test_hitl_placeholder_flags(self):
        hitl_rings = (RingType.RING_2, RingType.RING_4, RingType.RING_8, RingType.RING_10)
        for rt in hitl_rings:
            # 未注册为实现，用类标注入片数据校验 hitl_required 约定
            import importlib
            pkg = importlib.import_module(f"backend.executor.ring{int(rt.value.split('_')[1])}")
            cls = [v for v in vars(pkg).values()]
            executor_cls = [c for c in cls if isinstance(c, type) and hasattr(c, "hitl_required") and c.ring_type == rt]
            assert executor_cls, f"{rt.value} 应有占位执行体类"
            assert executor_cls[0].hitl_required is True, f"{rt.value} 应标注 HITL"

    def test_ring_type_hitl_gate(self):
        # 与 ring_type 枚举自带的 is_hitl_gate 保持一致
        for rt in (RingType.RING_2, RingType.RING_4, RingType.RING_8, RingType.RING_10):
            assert rt.is_hitl_gate is True
        for rt in (RingType.RING_1, RingType.RING_5, RingType.RING_6):
            assert rt.is_hitl_gate is False
