# -*- coding: utf-8 -*-
"""环3 标准通道（scope 路由 + 知识库合并）测试。

验证：
    1. scope 传参透传到 search（fake 捕获 scope）。
    2. 只有知识库literature文件进入文献候选，上传不自动等于已核验。
    3. 引导层源（chinese）返回 guide 条目进池。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor


class _CaptureLit:
    """捕获 search 调用的 scope/source_ids。"""

    def __init__(self):
        self.calls = []

    def search(self, query, max_results=10, scope=None, source_ids=None):
        from backend.common.lit import LitItem

        self.calls.append({"query": query, "scope": scope, "source_ids": source_ids})
        if scope == "chinese":
            # 引导层：返回 guide 条目
            return [LitItem(title="【NCPSSD】检索指引", venue="NCPSSD",
                            item_type="guide", language="zh", reliability="discovery",
                            sources=["ncpssd"], raw={"guide": True})]
        return [
            LitItem(title=f"Paper {query[:10]}", authors=["A"], year=2023, venue="J",
                    doi="10.1000/x.1", reliability="matched", sources=["crossref"]),
            LitItem(title=f"研究 {query[:10]}", authors=["B"], year=2024, venue="中文刊",
                    doi="", reliability="uncertain", language="zh", sources=["openalex"]),
        ]

    def verify_ref(self, ref):
        return {"ok": False, "reliability": "unverified", "evidence": {}, "item": None}


class _FakeSettings:
    enabled = False
    api_key = ""
    fallback_to_mock = True
    retry_max = 1
    timeout = 30


@pytest.fixture()
def env(monkeypatch):
    from backend.executor import ring3

    fake = _CaptureLit()
    monkeypatch.setattr(ring3, "get_lit_service", lambda: fake)
    monkeypatch.setattr(ring3, "get_llm_settings", lambda: _FakeSettings())
    monkeypatch.setattr(ring3, "_llm_expand_queries", lambda *a, **k: ["query1", "query2"])
    return fake


class TestRing3Scope:
    def test_scope_passed_to_search(self, env):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", scope="english")
        res = get_executor(3).execute(ctx)
        assert res.accept is True
        assert all(c["scope"] == "english" for c in env.calls), "scope 应透传到 search"

    def test_chinese_scope_guides_in_pool(self, env):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", scope="chinese")
        res = get_executor(3).execute(ctx)
        data = json.loads(res.output)
        # 引导条目进池（guide 类型保留），total > 0
        assert data["total"] >= 1
        assert all(i["reliability"] in ("matched", "discovery", "uncertain") for i in data["items"])

    def test_kb_files_merged(self, env):
        # 知识库文献可合并入池，但上传行为本身不能证明题录真实。
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", scope="english")
        ctx.kb_files = [
            {"file_id": "f1", "file_name": "deep.pdf",
             "metadata": {"title": "基于CNN的图像分割", "authors": ["张三"], "year": 2024,
                          "venue": "计算机学报", "doi": "", "kind": "literature"}},
        ]
        res = get_executor(3).execute(ctx)
        data = json.loads(res.output)
        titles = [i["title"] for i in data["items"]]
        assert "基于CNN的图像分割" in titles, "知识库文献应合并入池"
        kb_item = next(i for i in data["items"] if i["title"] == "基于CNN的图像分割")
        assert kb_item["reliability"] == "uncertain", "用户上传不得自动标为已核验"
        assert kb_item["gbt7714"], "知识库文献应有 GB/T 7714"

    def test_non_literature_kb_files_never_enter_literature_pool(self, env):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", scope="english")
        ctx.kb_files = [
            {
                "file_id": "raw-1",
                "file_name": "experiment.csv",
                "metadata": {"title": "实验原始数据", "kind": "raw_data"},
            },
            {
                "file_id": "code-1",
                "file_name": "analysis.py",
                "metadata": {"title": "分析脚本", "kind": "code"},
            },
        ]

        data = json.loads(get_executor(3).execute(ctx).output)
        titles = {item["title"] for item in data["items"]}

        assert "实验原始数据" not in titles
        assert "分析脚本" not in titles

    def test_default_scope_all(self, env):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        get_executor(3).execute(ctx)
        assert all(c["scope"] == "all" for c in env.calls)
