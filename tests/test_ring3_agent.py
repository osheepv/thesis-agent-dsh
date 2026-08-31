# -*- coding: utf-8 -*-
"""环3 Agent Loop 检索策略测试（H4-R3AL）。

验证：
    1. 只读工具的正确性（read_approved_topic/check_relevance/validate_query）。
    2. 检索词解析（合法JSON/文本包裹JSON/空列表报错）。
    3. Agent Loop 关闭时行为不变（不调用LLM）。
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("THESIS_TASK_STORE_MEMORY", "true")

from backend.common.aicoding.enums import Degree
from backend.executor.base import ExecContext
from backend.executor.ring3 import (
    Ring3LiteratureReviewExecutor,
    _literature_tools,
    _parse_search_strategy,
)


def _make_ctx(**kw) -> ExecContext:
    defaults = dict(
        theme="生成式人工智能辅助学术写作中的引用可信性保障机制研究",
        subject_field="计算机科学与技术",
        degree=Degree.BACHELOR,
        outline="",
        literature=[],
        results=[],
        project_memory={},
    )
    defaults.update(kw)
    return ExecContext(**defaults)


class TestLiteratureTools:
    def test_read_approved_topic(self):
        ctx = _make_ctx()
        tools = _literature_tools(ctx, ctx.theme)
        topic_tool = next(t for t in tools if t.name == "read_approved_topic")
        result = topic_tool.handler({})
        assert result["theme"] == ctx.theme
        assert result["subject_field"] == ctx.subject_field

    def test_read_project_memory_empty(self):
        ctx = _make_ctx(project_memory={})
        tools = _literature_tools(ctx, ctx.theme)
        mem_tool = next(t for t in tools if t.name == "read_project_memory")
        result = mem_tool.handler({})
        assert result["status"] == "empty"

    def test_check_relevance(self):
        ctx = _make_ctx()
        tools = _literature_tools(ctx, ctx.theme)
        rel_tool = next(t for t in tools if t.name == "check_relevance")
        result = rel_tool.handler({"title": "学术写作中的人工智能辅助与引用诚信保障"})
        assert "relevance_score" in result
        assert result["relevance_score"] >= 0

    def test_validate_query_valid(self):
        ctx = _make_ctx()
        tools = _literature_tools(ctx, ctx.theme)
        vq_tool = next(t for t in tools if t.name == "validate_query")
        result = vq_tool.handler({"query": "citation trustworthiness generative AI"})
        assert result["valid"] is True
        assert result["keyword_count"] > 0

    def test_validate_query_empty(self):
        ctx = _make_ctx()
        tools = _literature_tools(ctx, ctx.theme)
        vq_tool = next(t for t in tools if t.name == "validate_query")
        result = vq_tool.handler({"query": ""})
        assert result["valid"] is False


class TestParseSearchStrategy:
    def test_valid_json(self):
        content = json.dumps({"queries": ["检索词A", "query B", "关键词C"], "rationale": "test"})
        result = _parse_search_strategy(content)
        assert len(result) == 3
        assert result[0] == "检索词A"

    def test_json_in_text(self):
        content = '策略如下：{"queries": ["AI写作", "academic integrity"]} 以上。'
        result = _parse_search_strategy(content)
        assert len(result) == 2

    def test_empty_queries_raises(self):
        with pytest.raises(Exception, match="queries列表为空"):
            _parse_search_strategy(json.dumps({"queries": []}))

    def test_no_json_raises(self):
        with pytest.raises(Exception, match="无有效JSON"):
            _parse_search_strategy("没有JSON内容")


class TestAgentLoopDisabled:
    def test_disabled_no_agent_fields(self):
        """Agent Loop 关闭时不改变现有行为。"""
        ctx = _make_ctx(agent_loop_enabled=False)
        executor = Ring3LiteratureReviewExecutor()
        # 离线模式（LIT_ENABLED=false）返回空池，不调用LLM
        os.environ["THESIS_LIT_ENABLED"] = "false"
        try:
            result = executor.execute(ctx)
            evidence = result.evidence
            assert evidence["agent_loop"]["enabled"] is False
            assert evidence["agent_loop"]["turns"] == 0
        finally:
            os.environ["THESIS_LIT_ENABLED"] = "true"
