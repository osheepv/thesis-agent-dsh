# -*- coding: utf-8 -*-
"""环5/6 文献池注入测试。

验证：
    1. lit_pool_block：文献池 → [L序号] 注入文本块；空池 → 禁止引用提示。
    2. 环5/6 LLM prompt 包含文献池块（fake LLM client 捕获 prompt）。
    3. 环6 从正文提取 used_refs。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree
from backend.common.lit import lit_pool_block
from backend.executor import ExecContext, get_executor
from backend.executor.ring6_chapter import ChapterWriteResult


SAMPLE_POOL = [
    {"title": "Deep Learning for Vision", "authors": ["Alice", "Bob"], "year": 2023,
     "venue": "Journal of AI", "doi": "10.1000/demo.1", "reliability": "verified"},
    {"title": "面向小样本的图像识别", "authors": ["张三"], "year": 2024,
     "venue": "计算机学报", "doi": "", "reliability": "uncertain"},
]


class TestLitPoolBlock:
    def test_block_contains_refs(self):
        block = lit_pool_block(SAMPLE_POOL)
        assert "[L1]" in block
        assert "[L2]" in block
        assert "Deep Learning for Vision" in block
        assert "禁止引用池外" in block or "禁止" in block

    def test_empty_pool_warns(self):
        block = lit_pool_block([])
        assert "文献池为空" in block and "禁止" in block

    def test_max_items_truncates(self):
        many = [{"title": f"Item {i}"} for i in range(30)]
        block = lit_pool_block(many, max_items=10)
        assert "[L10]" in block, "应含第10条"
        assert "[L11]" not in block, "超出 max_items 不应出现"


class TestRing6PoolInjected:
    @pytest.fixture()
    def fake_llm(self, monkeypatch):
        """替换环6 的 LLM：捕获 prompt 并返回固定章节。"""
        from backend.executor import ring6_chapter as r6

        captured = {}

        def fake_generate_json(system, prompt, model_cls, **kwargs):
            captured["prompt"] = prompt
            return r6.LLMChapterWriteOut(
                theme="T", degree="MASTER",
                chapters=[
                    r6.ChapterDraft(
                        chapter_no=1, chapter_title="第1章 绪论",
                        content="## 1 引言\n根据 [L1] 的方法…[L2] 的改进。",
                        word_count=120,
                    )
                ],
                total_words=120,
            )

        monkeypatch.setattr(
            r6, "get_llm_client",
            lambda: type("C", (), {
                "generate_json": lambda self, system, prompt, model_cls, **kw: fake_generate_json(
                    system, prompt, model_cls, **kw
                )
            })(),
        )
        monkeypatch.setattr(r6, "get_llm_settings",
                            lambda: type("S", (), {"enabled": True, "api_key": "x", "retry_max": 1,
                                                   "fallback_to_mock": True, "timeout": 30})())
        return captured

    def test_prompt_includes_pool(self, fake_llm):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T",
                          literature=SAMPLE_POOL)
        res = get_executor(6).execute(ctx)
        prompt = fake_llm["prompt"]
        assert "[L1]" in prompt
        assert "[L2]" in prompt
        assert "Deep Learning for Vision" in prompt
        data = json.loads(res.output)
        assert data["used_refs"] == ["[L1]", "[L2]"], "应提取正文引用的 [L序号]"

    def test_empty_pool_prompt_forbids(self, fake_llm):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", literature=[])
        get_executor(6).execute(ctx)
        assert "文献池为空" in fake_llm["prompt"]
        assert "禁止" in fake_llm["prompt"]
