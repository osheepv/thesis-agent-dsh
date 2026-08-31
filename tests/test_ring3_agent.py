# -*- coding: utf-8 -*-
"""环3 Agent Loop 检索策略测试（H4-R3AL）。

验证：
    1. 只读工具的正确性（read_approved_topic/check_relevance/validate_query）。
    2. DeepSeek 检索词扩展与严格结构化输出解析。
    3. Agent Loop 只采信已读取上下文且逐条校验成功的查询。
    4. 离线模式不触发网络，正式编排传递 Agent 与项目记忆上下文。
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("THESIS_TASK_STORE_MEMORY", "true")

from application.service import uc_main_orchestration as orchestration_module
from application.service.uc_main_orchestration import MainOrchestration
from common.agent_loop import AgentLoopSettings, ModelToolCall, ModelTurn
from common.aicoding.enums import Degree
from common.aicoding.exception.biz_exception import BizException
from common.llm import StructuredOutputError
from executor import ring3
from executor.base import ExecContext, ExecResult


Ring3LiteratureReviewExecutor = ring3.Ring3LiteratureReviewExecutor
_literature_tools = ring3._literature_tools
_parse_search_strategy = ring3._parse_search_strategy


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


def _project_memory_payload() -> dict:
    return {
        "research_questions": ["如何降低论文智能体的虚假引用？"],
        "decisions": [],
        "supervisor_feedback": [],
        "terminology": [],
        "writing_style": None,
        "version_note": "ring3-agent-test",
    }


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
        content = (
            '策略如下：{"queries": ["AI写作引用可信性", '
            '"academic writing citation integrity", "生成式AI 学术诚信"]} 以上。'
        )
        result = _parse_search_strategy(content)
        assert len(result) == 3

    def test_empty_queries_raises(self):
        with pytest.raises(StructuredOutputError):
            _parse_search_strategy(json.dumps({"queries": []}))

    def test_no_json_raises(self):
        with pytest.raises(StructuredOutputError):
            _parse_search_strategy("没有JSON内容")

    @pytest.mark.parametrize("payload", [[], None, "not-an-object"])
    def test_top_level_non_object_fails_closed(self, payload):
        with pytest.raises(StructuredOutputError):
            _parse_search_strategy(json.dumps(payload))

    def test_non_string_query_fails_closed(self):
        content = json.dumps({
            "queries": [
                "AI写作引用可信性",
                42,
                "academic writing citation integrity",
            ]
        })
        with pytest.raises(StructuredOutputError):
            _parse_search_strategy(content)

    @pytest.mark.parametrize("queries", [
        ["AI写作引用可信性"],
        ["AI写作引用可信性", "academic writing citation integrity"],
    ])
    def test_fewer_than_three_queries_fails_closed(self, queries):
        with pytest.raises(StructuredOutputError):
            _parse_search_strategy(json.dumps({"queries": queries}))

    def test_more_than_five_or_duplicate_queries_fails_closed(self):
        with pytest.raises(StructuredOutputError, match="最多"):
            _parse_search_strategy(json.dumps({
                "queries": [f"valid academic query {index}" for index in range(6)]
            }))
        with pytest.raises(StructuredOutputError, match="重复"):
            _parse_search_strategy(json.dumps({
                "queries": ["引用可信性", "citation integrity", "引用可信性"]
            }, ensure_ascii=False))


def test_llm_expand_queries_calls_generate_json_and_returns_three_valid_queries(
    monkeypatch,
):
    queries = [
        "生成式人工智能 学术写作 引用可信性",
        "generative AI academic writing citation trustworthiness",
        "large language model scholarly integrity reference verification",
    ]
    client = MagicMock()
    client.generate_json.side_effect = lambda **kwargs: kwargs["model_cls"](
        queries=queries
    )
    monkeypatch.setattr(
        ring3,
        "get_llm_settings",
        lambda: SimpleNamespace(enabled=True, api_key="test-key"),
    )
    monkeypatch.setattr(ring3, "get_llm_client", lambda: client)

    result = ring3._llm_expand_queries(  # noqa: SLF001 - 回归内部安全契约
        "计算机科学与技术",
        "生成式人工智能辅助学术写作中的引用可信性保障机制研究",
    )

    assert result == queries
    client.generate_json.assert_called_once()
    validator = next(
        tool for tool in _literature_tools(_make_ctx(), _make_ctx().theme)
        if tool.name == "validate_query"
    )
    assert all(validator.handler({"query": query})["valid"] for query in result)


class TestBuildSearchStrategy:
    queries = [
        "生成式人工智能 学术写作 引用可信性",
        "generative AI academic writing citation trustworthiness",
        "large language model scholarly integrity reference verification",
    ]

    @staticmethod
    def _client(turns):
        return type("Client", (), {
            "complete_with_tools": staticmethod(lambda *_: next(turns)),
        })()

    def test_reads_approved_context_and_validates_every_final_query(self, monkeypatch):
        turns = iter([
            ModelTurn(tool_calls=(
                ModelToolCall("topic", "read_approved_topic", "{}"),
                ModelToolCall("memory", "read_project_memory", "{}"),
            )),
            ModelTurn(tool_calls=tuple(
                ModelToolCall(
                    f"validate-{index}",
                    "validate_query",
                    json.dumps({"query": query}, ensure_ascii=False),
                )
                for index, query in enumerate(self.queries, start=1)
            )),
            ModelTurn(content=json.dumps({"queries": self.queries}, ensure_ascii=False)),
        ])
        monkeypatch.setattr(ring3, "get_llm_client", lambda: self._client(turns))
        ctx = _make_ctx(project_memory=_project_memory_payload())

        result = ring3._build_search_strategy(  # noqa: SLF001
            ctx,
            ctx.theme,
            AgentLoopSettings(max_turns=3),
        )

        assert result["queries"] == self.queries
        assert result["agent_context_reads"] == ["approved_topic", "project_memory"]
        assert result["agent_validated_queries"] == self.queries

    @pytest.mark.parametrize(
        ("tool_calls", "message"),
        [
            (
                [ModelToolCall("memory", "read_project_memory", "{}")],
                "未读取已批准选题",
            ),
            (
                [ModelToolCall("topic", "read_approved_topic", "{}")],
                "未读取已批准项目记忆",
            ),
        ],
    )
    def test_rejects_missing_required_context_read(
        self, monkeypatch, tool_calls, message
    ):
        validation_calls = [
            ModelToolCall(
                f"validate-{index}",
                "validate_query",
                json.dumps({"query": query}, ensure_ascii=False),
            )
            for index, query in enumerate(self.queries, start=1)
        ]
        turns = iter([
            ModelTurn(tool_calls=tuple(tool_calls + validation_calls)),
            ModelTurn(content=json.dumps({"queries": self.queries}, ensure_ascii=False)),
        ])
        monkeypatch.setattr(ring3, "get_llm_client", lambda: self._client(turns))
        ctx = _make_ctx(project_memory=_project_memory_payload())

        with pytest.raises(StructuredOutputError):
            ring3._build_search_strategy(  # noqa: SLF001
                ctx,
                ctx.theme,
                AgentLoopSettings(max_turns=2),
            )

    def test_rejects_final_query_without_successful_validation(self, monkeypatch):
        turns = iter([
            ModelTurn(tool_calls=(
                ModelToolCall("topic", "read_approved_topic", "{}"),
                ModelToolCall("memory", "read_project_memory", "{}"),
                ModelToolCall(
                    "validate-1",
                    "validate_query",
                    json.dumps({"query": self.queries[0]}, ensure_ascii=False),
                ),
                ModelToolCall(
                    "validate-2",
                    "validate_query",
                    json.dumps({"query": self.queries[1]}, ensure_ascii=False),
                ),
            )),
            ModelTurn(content=json.dumps({"queries": self.queries}, ensure_ascii=False)),
        ])
        monkeypatch.setattr(ring3, "get_llm_client", lambda: self._client(turns))
        ctx = _make_ctx(project_memory=_project_memory_payload())

        with pytest.raises(StructuredOutputError):
            ring3._build_search_strategy(  # noqa: SLF001
                ctx,
                ctx.theme,
                AgentLoopSettings(max_turns=2),
            )


class TestAgentLoopDisabled:
    def test_offline_mode_never_calls_llm_or_literature_network(self, monkeypatch):
        """离线模式直接返回空池，且 evidence 只陈述真实离线状态。"""
        ctx = _make_ctx(agent_loop_enabled=False)
        executor = Ring3LiteratureReviewExecutor()
        service = MagicMock()
        service.search.side_effect = AssertionError("离线模式不应调用文献网络")
        client = MagicMock()
        client.generate_json.side_effect = AssertionError("离线模式不应调用LLM")
        monkeypatch.setattr(ring3, "_LIT_ENABLED", False)
        monkeypatch.setattr(ring3, "get_lit_service", lambda: service)
        monkeypatch.setattr(
            ring3,
            "get_llm_settings",
            lambda: SimpleNamespace(enabled=True, api_key="test-key"),
        )
        monkeypatch.setattr(ring3, "get_llm_client", lambda: client)

        result = executor.execute(ctx)

        service.search.assert_not_called()
        client.generate_json.assert_not_called()
        assert result.evidence == {
            "sources": [],
            "fetched": 0,
            "note": "THESIS_LIT_ENABLED=false",
            "agent_loop": {
                "enabled": False,
                "status": "skipped_literature_disabled",
                "turns": 0,
                "tool_calls": 0,
            },
        }
        assert json.loads(result.output)["search_queries"] == []


class TestOrchestrationWiring:
    @staticmethod
    def _approved_memory(orchestration: MainOrchestration, task_id: str) -> dict:
        created = orchestration.create_project_memory(
            task_id, _project_memory_payload()
        ).data
        orchestration.review_project_memory(
            task_id, created["artifact_id"], approved=True
        )
        active = orchestration._active_project_memory(task_id)  # noqa: SLF001
        assert active is not None
        return active.payload

    @staticmethod
    def _patch_llm_capability(monkeypatch, *, supports_tools: bool) -> None:
        from common import llm

        settings = SimpleNamespace(
            supports_tools=supports_tools,
            model="deepseek-test",
        )
        monkeypatch.setattr(llm, "get_llm_settings", lambda: settings)
        monkeypatch.setattr(
            orchestration_module,
            "get_llm_settings",
            lambda: settings,
            raising=False,
        )

    def test_ensure_literature_passes_agent_flag_and_approved_memory(
        self, monkeypatch
    ):
        monkeypatch.setenv("THESIS_AGENT_LOOP_ENABLED", "true")
        self._patch_llm_capability(monkeypatch, supports_tools=True)
        orchestration = MainOrchestration()
        task_id = orchestration.create_task(
            "环3正式编排接线",
            Degree.BACHELOR,
            "计算机科学与技术",
            session_id="ring3-wiring",
        ).data["task_id"]
        approved_memory = self._approved_memory(orchestration, task_id)
        rec = orchestration._store.get(task_id)  # noqa: SLF001
        captured = {}

        class FakeRing3:
            def execute(self, ctx):
                captured["ctx"] = ctx
                return ExecResult(output=json.dumps({
                    "items": [],
                    "search_queries": [],
                }))

        monkeypatch.setattr(
            orchestration_module,
            "get_executor",
            lambda ring_no: FakeRing3() if ring_no == 3 else None,
        )

        assert orchestration._ensure_literature(rec, rec.title) == []  # noqa: SLF001
        assert captured["ctx"].agent_loop_enabled is True
        assert captured["ctx"].project_memory == approved_memory

    def test_ensure_literature_rejects_model_without_tools(self, monkeypatch):
        monkeypatch.setenv("THESIS_AGENT_LOOP_ENABLED", "true")
        self._patch_llm_capability(monkeypatch, supports_tools=False)
        orchestration = MainOrchestration()
        task_id = orchestration.create_task(
            "环3Tools能力门禁",
            Degree.BACHELOR,
            "计算机科学与技术",
            session_id="ring3-tools-gate",
        ).data["task_id"]
        rec = orchestration._store.get(task_id)  # noqa: SLF001
        fake_executor = MagicMock()
        monkeypatch.setattr(
            orchestration_module,
            "get_executor",
            lambda ring_no: fake_executor,
        )

        with pytest.raises(BizException) as exc_info:
            orchestration._ensure_literature(rec, rec.title)  # noqa: SLF001
        assert "Tools" in str(exc_info.value)
        fake_executor.execute.assert_not_called()

    def test_ensure_literature_surfaces_enabled_agent_failure(self, monkeypatch):
        monkeypatch.setenv("THESIS_AGENT_LOOP_ENABLED", "true")
        self._patch_llm_capability(monkeypatch, supports_tools=True)
        orchestration = MainOrchestration()
        task_id = orchestration.create_task(
            "环3Agent失败显式上报",
            Degree.BACHELOR,
            "计算机科学与技术",
            session_id="ring3-agent-failure",
        ).data["task_id"]
        rec = orchestration._store.get(task_id)  # noqa: SLF001

        class FailingRing3:
            def execute(self, ctx):
                raise StructuredOutputError("最终检索词未通过校验")

        monkeypatch.setattr(
            orchestration_module,
            "get_executor",
            lambda ring_no: FailingRing3(),
        )

        with pytest.raises(BizException, match="Agent执行失败"):
            orchestration._ensure_literature(rec, rec.title)  # noqa: SLF001
        assert rec.ring3 is None
