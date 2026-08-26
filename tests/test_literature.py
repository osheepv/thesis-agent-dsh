# -*- coding: utf-8 -*-
"""环3/环8 文献环节单元测试。

Mock 掉 LiteratureService（不依赖真实 API/网络），验证：
    1. 环3 文献调研：检索→证据池→GB/T 7714 分类/可靠度。
    2. 环8 引用校验：多源核验→通过/待复核/伪引判定→回退目标。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor


# ---------------------------------------------------------------------
# 环3 文献调研（Mock 检索）
# ---------------------------------------------------------------------
class FakeLitService:
    """假文献检索：返回固定条目，不访问网络。"""

    def search(self, query: str, max_results: int = 10, scope=None, source_ids=None):
        from backend.common.lit import LitItem

        return [
            LitItem(
                title="Deep Learning for Vision",
                authors=["Alice", "Bob"],
                year=2023,
                venue="Journal of AI",
                doi="10.1000/demo.123",
                abstract="A survey of deep learning methods.",
                citation_count=10,
                item_type="article",
                language="en",
                reliability="verified",
                sources=["crossref"],
            ),
            LitItem(
                title="面向小样本的图像识别方法研究",
                authors=["张三"],
                year=2024,
                venue="计算机学报",
                doi="",
                abstract="中文文献示例。",
                reliability="uncertain",
                language="zh",
                sources=["openalex"],
            ),
        ]

    def verify_ref(self, ref):
        # 环8 用：标题含"存在" → 命中；否则未命中
        title = ref.get("title", "")
        if "存在" in title:
            from backend.common.lit import LitItem

            return {
                "ok": True,
                "reliability": "verified",
                "evidence": {"source": "crossref"},
                "item": LitItem(
                    title=title, authors=["Alice"], year=2023, venue="Journal",
                    doi="10.1000/exist.1", reliability="verified", sources=["crossref"],
                ).to_dict(),
            }
        return {
            "ok": False,
            "reliability": "unverified",
            "evidence": {"reason": "未命中", "checked_sources": ["crossref", "openalex"]},
            "item": None,
        }


@pytest.fixture()
def fake_lit(monkeypatch):
    """替换环3/环8 的 get_lit_service 返回值。"""
    from backend.executor import ring3, ring8

    monkeypatch.setattr(ring3, "get_lit_service", lambda: FakeLitService())
    monkeypatch.setattr(ring8, "get_lit_service", lambda: FakeLitService())
    # 环3 内 LLM 扩展也禁用（不调用 API）
    monkeypatch.setattr(ring3, "get_llm_settings", lambda: type("S", (), {"enabled": False, "api_key": ""})())
    monkeypatch.setattr(ring3, "_llm_expand_queries", lambda *a, **k: [])


class TestRing3Literature:
    def test_pool_built_with_categories(self, fake_lit):
        ctx = ExecContext(subject_field="计算机视觉", degree=Degree.MASTER, theme="T")
        res = get_executor(3).execute(ctx)
        assert res.accept is True
        data = json.loads(res.output)
        assert data["total"] == 2
        categories = {it["category"] for it in data["items"]}
        assert categories, "应有分类"
        # 每条都有 GB/T 7714 输出
        assert all(it["gbt7714"] for it in data["items"])
        # 可靠度标记存在（en verified / zh uncertain）
        assert any(it["reliability"] in ("verified", "matched") for it in data["items"])
        assert any(it["reliability"] == "uncertain" for it in data["items"])

    def test_degree_target_recorded(self, fake_lit):
        ctx = ExecContext(subject_field="NLP", degree=Degree.PHD, theme="T")
        data = json.loads(get_executor(3).execute(ctx).output)
        assert data["target_count"] > 0
        assert data["summary"], "应有说明（来源/补全建议）"

    def test_relevance_ranking_beats_metadata_reliability(self):
        from backend.executor.ring3 import LiteratureItem, _rank_by_relevance

        items = [
            LiteratureItem(
                title="工业零部件表面缺陷检测算法优化研究",
                reliability="verified",
            ),
            LiteratureItem(
                title="高校学术不端与毕业论文查重机制研究",
                abstract="讨论场景适配和学术诚信治理。",
                reliability="matched",
            ),
            LiteratureItem(
                title="地基基础检测技术优化研究",
                reliability="verified",
            ),
            LiteratureItem(
                title="Natural Scene Text Detection Algorithm",
                reliability="verified",
            ),
            LiteratureItem(
                title="Text Plagiarism Detection for Academic Writing",
                reliability="matched",
            ),
        ]

        ranked = _rank_by_relevance(
            items,
            "基于场景适配的高校学术不端检测算法优化研究——以本科毕业论文查重为例",
            "人工智能治理与学术信息管理 plagiarism academic writing",
        )

        assert ranked[0].title == "高校学术不端与毕业论文查重机制研究"
        assert ranked[0].relevance_score >= 0.12
        assert ranked[0].relevance_score > ranked[1].relevance_score
        plagiarism = next(
            item for item in ranked if "Plagiarism" in item.title
        )
        scene_detection = next(
            item for item in ranked if "Natural Scene" in item.title
        )
        assert plagiarism.relevance_score > scene_detection.relevance_score


class TestRing8Check:
    def test_refs_verified(self, fake_lit):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER)
        ctx.references = [{"title": "存在的研究", "authors": ["Alice"], "year": 2023}]
        res = get_executor(8).execute(ctx)
        data = json.loads(res.output)
        assert res.accept is True
        assert data["passed"] == 1
        assert data["failed"] == 0
        assert data["items"][0]["gbt7714"], "通过条目应输出 GB/T 7714"
        assert res.fallbackTo is None

    def test_fake_ref_detected(self, fake_lit):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER)
        ctx.references = [{"title": "完全虚构的论文标题甲乙丙", "authors": ["王五"]}]
        res = get_executor(8).execute(ctx)
        data = json.loads(res.output)
        assert res.accept is False
        assert data["failed"] == 1
        # 伪引 → 回退到环3 补文献
        assert res.fallbackTo == 3

    def test_no_refs_skips(self, fake_lit):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER)
        res = get_executor(8).execute(ctx)
        data = json.loads(res.output)
        assert data["total"] == 0
        assert "未提供" in data["summary"]
