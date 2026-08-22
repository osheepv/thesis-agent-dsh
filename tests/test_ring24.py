# -*- coding: utf-8 -*-
"""环2/环4 新颖度评审测试。

验证：
    1. 环2 新颖度（fake 检索 + fake LLM）：HIGH 放行 / LOW 回退环1 / 检索失败走规则。
    2. 环4 综述评审：池内高度重叠 → 需重评估回退环2；空池 → 需补充回退环3；顺 → 放行。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor


# ---------------------------------------------------------------------
# fake 组件
# ---------------------------------------------------------------------
class FakeLitService:
    """环2 用的假检索：按查询词决定命中。"""

    def search(self, query: str, max_results: int = 10):
        from backend.common.lit import LitItem

        if "热门" in query:
            return [
                LitItem(title=f"{query}实验研究", authors=["张三"], year=2024,
                        venue="计算机学报", doi="10.1000/hot.1", reliability="matched"),
                LitItem(title=f"基于{query}的改进", authors=["李四"], year=2023,
                        venue="软件学报", doi="10.1000/hot.2", reliability="matched"),
            ]
        return [
            LitItem(title="完全不同的边缘研究", authors=["王五"], year=2020,
                    venue="其他", doi="", reliability="uncertain"),
        ]


class _FakeSettings:
    enabled = True
    api_key = "x"
    retry_max = 1
    fallback_to_mock = True
    timeout = 30


class _FakeLLM:
    """环2/4 的假 LLM。mode: high/low/顺/需补充/需重评估。"""

    def __init__(self, mode: str):
        self.mode = mode

    def generate_json(self, system, prompt, model_cls, **kw):
        if "novelty_level" in model_cls.model_fields.keys():  # 环2
            if self.mode == "low":
                return model_cls(novelty_level="LOW", differ_from_prior="已被大量研究",
                                 risk_notes=["无空间"], recommendation="回退环1 换题")
            return model_cls(novelty_level="HIGH", differ_from_prior="聚焦边缘场景",
                             risk_notes=["覆盖待核"], recommendation="放行")
        # 环4
        if self.mode == "需重评估":
            return model_cls(verdict="需重评估", risks=["创新点被包住"], recommendation="回退环2")
        if self.mode == "需补充":
            return model_cls(verdict="需补充", risks=["有重叠"], recommendation="补差异化")
        return model_cls(verdict="顺", risks=[], recommendation="放行至大纲")


@pytest.fixture()
def ring2_env(monkeypatch):
    from backend.executor import ring2

    monkeypatch.setattr(ring2, "get_lit_service", lambda: FakeLitService())
    monkeypatch.setattr(ring2, "get_llm_settings", lambda: _FakeSettings())
    return ring2


@pytest.fixture()
def ring4_env(monkeypatch):
    from backend.executor import ring4

    # 不触发检索（环4 只用池）
    monkeypatch.setattr(ring4, "get_llm_settings", lambda: _FakeSettings())
    return ring4


# ---------------------------------------------------------------------
# 环2 新颖度
# ---------------------------------------------------------------------
class TestRing2Novelty:
    def test_high_passes(self, ring2_env, monkeypatch):
        monkeypatch.setattr(ring2_env, "get_llm_client", lambda: _FakeLLM("high"))
        ctx = ExecContext(subject_field="计算机视觉", degree=Degree.MASTER,
                          theme="基于深度学习的图像识别研究")
        res = get_executor(2).execute(ctx)
        assert res.accept is True
        data = json.loads(res.output)
        assert data["novelty_level"] == "HIGH"
        assert res.fallbackTo is None
        assert data["similar_count"] >= 0

    def test_low_falls_back_ring1(self, ring2_env, monkeypatch):
        monkeypatch.setattr(ring2_env, "get_llm_client", lambda: _FakeLLM("low"))
        ctx = ExecContext(subject_field="热门方向", degree=Degree.MASTER,
                          theme="热门方向研究")
        res = get_executor(2).execute(ctx)
        assert res.accept is False
        assert res.fallbackTo == 1, "LOW 应回退环1 换题"
        assert json.loads(res.output)["novelty_level"] == "LOW"

    def test_rule_fallback_when_llm_off(self, ring2_env, monkeypatch):
        # LLM 关闭走规则兜底（检索命中 0）= HIGH
        monkeypatch.setattr(ring2_env, "get_llm_settings",
                            lambda: type("S", (), {"enabled": False, "api_key": "",
                                                   "fallback_to_mock": True, "retry_max": 1})())
        ctx = ExecContext(subject_field="新领域", degree=Degree.BACHELOR,
                          theme="全新方向研究")
        res = get_executor(2).execute(ctx)
        assert res.accept is True


# ---------------------------------------------------------------------
# 环4 综述评审
# ---------------------------------------------------------------------
def _pool(titles):
    return [{"title": t, "authors": ["X"], "year": 2023, "venue": "J", "doi": ""} for t in titles]


class TestRing4Review:
    def test_overlap_falls_back_ring2(self, ring4_env, monkeypatch):
        monkeypatch.setattr(ring4_env, "get_llm_client", lambda: _FakeLLM("需重评估"))
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER,
                          theme="基于深度学习的图像识别研究",
                          literature=_pool(["基于深度学习的图像识别研究与应用",
                                            "深度学习图像识别算法综述"]))
        res = get_executor(4).execute(ctx)
        assert res.accept is False
        assert res.fallbackTo == 2, "创新点被包住应回退环2"

    def test_empty_pool_needs_supplement(self, ring4_env, monkeypatch):
        monkeypatch.setattr(ring4_env, "get_llm_client", lambda: _FakeLLM("需补充"))
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", literature=[])
        res = get_executor(4).execute(ctx)
        assert res.accept is False
        assert res.fallbackTo == 3, "空池应回退环3 补文献"

    def test_clear_passes(self, ring4_env, monkeypatch):
        monkeypatch.setattr(ring4_env, "get_llm_client", lambda: _FakeLLM("顺"))
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER,
                          theme="面向小样本的遥感图像识别",
                          literature=_pool(["自然语言处理综述", "推荐系统方法"]))
        res = get_executor(4).execute(ctx)
        assert res.accept is True
        assert res.fallbackTo is None
        assert json.loads(res.output)["overlap_count"] == 0
