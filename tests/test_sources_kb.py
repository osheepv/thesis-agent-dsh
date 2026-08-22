# -*- coding: utf-8 -*-
"""标准检索通道（Source Registry）+ 会话知识库测试。

验证：
    1. 源注册表：登记/scope 解析/非法源拒绝/引导层源始终提供。
    2. LiteratureService 路由：english 只查 API 层、chinese 走引导层（guide 条目）。
    3. 知识库：上传/列表/删除/会话路径。
"""
from __future__ import annotations

import json
import os

import pytest

from backend.common.sources import (
    get_enabled_sources,
    get_source,
    registry_summary,
    resolve_scope,
)


# ---------------------------------------------------------------------
# 源注册表
# ---------------------------------------------------------------------
class TestSourceRegistry:
    def test_registry_has_core_sources(self):
        for sid in ("crossref", "openalex", "semanticscholar", "ncpssd", "chinaxiv", "metaso"):
            assert get_source(sid) is not None, f"{sid} 应登记"

    def test_scope_english(self):
        sids = resolve_scope("english")
        assert "crossref" in sids and "openalex" in sids
        assert "ncpssd" not in sids, "英文范围不应含中文源"

    def test_scope_chinese_includes_guides(self):
        sids = resolve_scope("chinese")
        assert "ncpssd" in sids, "引导层源应始终提供"
        assert "chinaxiv" in sids

    def test_unknown_source_rejected(self):
        with pytest.raises(ValueError):
            resolve_scope(source_ids=["not-a-source"])

    def test_summary_has_metadata(self):
        rows = registry_summary()
        assert any(r["source_id"] == "crossref" and r["enabled"] for r in rows)
        assert any(r["source_id"] == "ncpssd" and not r["enabled"] for r in rows), "ncpssd 应登记但未启用 API"


# ---------------------------------------------------------------------
# LiteratureService 路由（Mock httpx，不真调 API）
# ---------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, data, status=200):
        self._d = data
        self.status_code = status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """假 httpx：crossref/openalex 返回英文条目；S2 返回空。"""

    def get(self, url, params=None):
        parts = []
        if "crossref.org" in url:
            for i in range(2):
                parts.append({
                    "title": [f"Paper {i} on {params.get('query.bibliographic', '')}"],
                    "author": [{"given": "A", "family": "Uthor"}],
                    "published-print": {"date-parts": [[2024]]},
                    "container-title": ["Journal"],
                    "DOI": f"10.1000/cr.{i}",
                    "type": "journal-article",
                    "is-referenced-by-count": 3,
                })
        elif "openalex.org" in url:
            for i in range(1):
                parts.append({
                    "display_name": f"OpenAlex hit {params.get('search', '')}",
                    "publication_year": 2023,
                    "authorships": [{"display_name": "B"}],
                    "primary_location": {"source": {"display_name": "Venue"}},
                    "doi": "https://doi.org/10.1000/oa.1",
                    "type": "article",
                    "cited_by_count": 5,
                    "abstract_inverted_index": None,
                })
        elif "semanticscholar.org" in url:
            parts = []
        return _FakeResponse({"message": {"items": parts}} if "crossref.org" in url else
                             ({"results": parts} if "openalex.org" in url else {"data": []}))
        if "crossref.org" in url:
            return _FakeResponse({"message": {"items": parts}})
        if "openalex.org" in url:
            return _FakeResponse({"results": parts})
        return _FakeResponse({"data": []})


class TestLiteratureRouting:
    def test_english_search_real_only(self, monkeypatch):
        from backend.common import lit

        svc = lit.LiteratureService()
        svc._client = _FakeClient()
        items = svc.search("vision", scope="english", max_results=10)
        assert all(i.item_type != "guide" for i in items), "英文范围不应有引导条目"
        assert any("crossref" in i.sources for i in items)

    def test_chinese_search_guides(self, monkeypatch):
        from backend.common import lit

        svc = lit.LiteratureService()
        svc._client = _FakeClient()
        items = svc.search("图像分割", scope="chinese", max_results=10)
        guides = [i for i in items if i.item_type == "guide"]
        assert guides, "中文范围应返回引导条目"
        assert any("ncpssd" in i.sources for i in guides)
        assert any("metaso" in i.sources for i in guides)

    def test_all_scope_mixed(self, monkeypatch):
        from backend.common import lit

        svc = lit.LiteratureService()
        svc._client = _FakeClient()
        items = svc.search("test", max_results=20)
        assert any(i.item_type == "guide" for i in items), "all 应含引导"

    def test_unknown_source_via_service(self, monkeypatch):
        from backend.common import lit

        svc = lit.LiteratureService()
        with pytest.raises(ValueError):
            svc.search("x", source_ids=["bad"])


# ---------------------------------------------------------------------
# 知识库（临时目录）
# ---------------------------------------------------------------------
class TestKnowledgeStore:
    def test_save_list_delete(self, tmp_path):
        from backend.knowledge.store import KnowledgeStore

        store = KnowledgeStore(root=tmp_path / "kb")
        rec = store.save_document("sess1", "paper.pdf", b"%PDF-content",
                                  metadata={"title": "T", "authors": ["A"]})
        assert rec["file_id"]
        assert os.path.exists(rec["file_path"])

        docs = store.list_documents("sess1")
        assert len(docs) == 1
        assert docs[0]["metadata"]["title"] == "T"

        assert store.delete_document("sess1", rec["file_id"]) is True
        assert store.list_documents("sess1") == []

    def test_bad_ext_rejected(self, tmp_path):
        from backend.knowledge.store import KnowledgeStore

        store = KnowledgeStore(root=tmp_path / "kb")
        with pytest.raises(ValueError):
            store.save_document("s1", "virus.exe", b"x")

    def test_session_path_created(self, tmp_path):
        from backend.knowledge.store import KnowledgeStore

        store = KnowledgeStore(root=tmp_path / "kb")
        p = store.session_path("sess-x")
        assert os.path.isdir(p)
