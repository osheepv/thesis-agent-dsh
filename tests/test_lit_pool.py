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

    def test_ring6_resumes_from_chapter_checkpoint(self, fake_llm):
        ctx = ExecContext(
            subject_field="CV",
            degree=Degree.BACHELOR,
            theme="T",
            literature=SAMPLE_POOL,
            outline=json.dumps({"chapters": [
                {"level": 1, "number": "第1章", "title": "绪论"},
                {"level": 1, "number": "第2章", "title": "方法"},
            ]}, ensure_ascii=False),
        )
        ctx.chapter_checkpoint = [{
            "chapter_no": 1,
            "chapter_title": "第1章 绪论",
            "content": "## 1 引言\n已保存正文 [L1]。",
            "word_count": 12,
        }]
        saved = []
        ctx.chapter_checkpoint_callback = lambda chapters: saved.append(len(chapters))

        result = get_executor(6).execute(ctx)

        data = json.loads(result.output)
        assert len(data["chapters"]) == 2
        assert data["chapters"][0]["content"] == "## 1 引言\n已保存正文 [L1]。"
        assert saved == [2]

    def test_ring6_expands_short_chapter_before_checkpoint(self, monkeypatch):
        from backend.executor import ring6_chapter as r6

        calls = []

        class ExpandingLLM:
            def generate_json(self, **kwargs):
                calls.append(kwargs["prompt"])
                content = (
                    "短正文 [L1]"
                    if len(calls) == 1
                    else "## 分析\n" + ("可信学术正文 [L1]。" * 1200)
                )
                return r6.LLMChapterWriteOut(
                    theme="T",
                    degree="BACHELOR",
                    chapters=[r6.ChapterDraft(
                        chapter_no=1,
                        chapter_title="第1章 绪论",
                        content=content,
                        word_count=len(content),
                    )],
                    total_words=len(content),
                )

        monkeypatch.setattr(r6, "get_llm_client", lambda: ExpandingLLM())
        monkeypatch.setattr(
            r6,
            "get_llm_settings",
            lambda: type("S", (), {
                "enabled": True,
                "api_key": "x",
                "fallback_to_mock": False,
            })(),
        )
        ctx = ExecContext(
            subject_field="CV",
            degree=Degree.BACHELOR,
            theme="T",
            literature=SAMPLE_POOL,
            outline=json.dumps({"chapters": [
                {"level": 1, "number": "第1章", "title": "绪论"},
            ]}, ensure_ascii=False),
        )
        ctx.enforce_chapter_minimum = True
        saved = []
        ctx.chapter_checkpoint_callback = lambda chapters: saved.append(chapters)

        result = get_executor(6).execute(ctx)

        data = json.loads(result.output)
        assert len(calls) == 2
        assert "增量补写" in calls[1]
        assert data["chapters"][0]["content"].startswith("短正文 [L1]")
        assert data["total_words"] >= Degree.BACHELOR.min_word_requirement
        assert len(saved) == 1

    def test_ring6_dynamic_target_allows_overachieving_prior_chapters(self, monkeypatch):
        from backend.executor import ring6_chapter as r6

        calls = []

        class FinalChapterClient:
            def generate_json(self, **kwargs):
                calls.append(kwargs["prompt"])
                content = "结论分析。" * 600
                return r6.LLMChapterWriteOut(
                    theme="T",
                    degree="MASTER",
                    chapters=[r6.ChapterDraft(
                        chapter_no=6,
                        chapter_title="第6章 结论",
                        content=content,
                        word_count=len(content),
                    )],
                    total_words=len(content),
                )

        monkeypatch.setattr(r6, "get_llm_client", lambda: FinalChapterClient())
        monkeypatch.setattr(
            r6,
            "get_llm_settings",
            lambda: type("S", (), {
                "enabled": True,
                "api_key": "x",
                "fallback_to_mock": False,
            })(),
        )
        outline = {
            "chapters": [
                {"level": 1, "number": f"第{number}章", "title": f"章节{number}"}
                for number in range(1, 7)
            ]
        }
        ctx = ExecContext(
            subject_field="AI",
            degree=Degree.MASTER,
            theme="T",
            outline=json.dumps(outline, ensure_ascii=False),
        )
        ctx.enforce_chapter_minimum = True
        ctx.chapter_checkpoint = [
            {
                "chapter_no": number,
                "chapter_title": f"第{number}章",
                "content": "既有章节。" * 1200,
                "word_count": 6000,
            }
            for number in range(1, 6)
        ]

        result = get_executor(6).execute(ctx)

        data = json.loads(result.output)
        assert len(calls) == 1
        assert data["chapters"][-1]["chapter_no"] == 6
        assert data["total_words"] >= Degree.MASTER.min_word_requirement
    def test_ring6_bounded_agent_plan_uses_tool_and_reaches_chapter_prompt(
        self, monkeypatch
    ):
        from common.agent_loop import ModelToolCall, ModelTurn
        from backend.executor import ring6_chapter as r6

        class PlanningClient:
            def __init__(self):
                self.plan_calls = 0
                self.chapter_prompts = []

            def complete_with_tools(self, messages, tools, max_output_tokens):
                self.plan_calls += 1
                if self.plan_calls == 1:
                    return ModelTurn(tool_calls=(ModelToolCall(
                        "plan-tool-1",
                        "read_approved_context",
                        '{"kind":"outline"}',
                    ),))
                if self.plan_calls == 2:
                    return ModelTurn(tool_calls=(
                        ModelToolCall(
                            "plan-tool-2",
                            "check_citation",
                            '{"marker":"[L1]"}',
                        ),
                        ModelToolCall(
                            "plan-tool-3",
                            "check_citation",
                            '{"marker":"[L2]"}',
                        ),
                    ))
                return ModelTurn(content="Plan ready.\n" + json.dumps({
                    "chapter_plans": [
                        {
                            "chapter_no": 1,
                            "objectives": ["解释研究背景"],
                            "suggested_refs": ["[L1]"],
                            "evidence_gaps": [],
                        },
                        {
                            "chapter_no": 2,
                            "objectives": ["说明方法设计"],
                            "suggested_refs": ["[L2]"],
                            "evidence_gaps": [],
                        },
                    ],
                    "global_notes": ["不得使用池外文献"],
                }, ensure_ascii=False))

            def generate_json(self, **kwargs):
                self.chapter_prompts.append(kwargs["prompt"])
                chapter_no = len(self.chapter_prompts)
                return r6.LLMChapterWriteOut(
                    theme="T",
                    degree="BACHELOR",
                    chapters=[r6.ChapterDraft(
                        chapter_no=chapter_no,
                        chapter_title=f"第{chapter_no}章",
                        content=f"## 正文\n计划约束下的正文 [L{chapter_no}]。",
                        word_count=20,
                    )],
                    total_words=20,
                )

        client = PlanningClient()
        monkeypatch.setattr(r6, "get_llm_client", lambda: client)
        monkeypatch.setattr(
            r6,
            "get_llm_settings",
            lambda: type("S", (), {
                "enabled": True,
                "api_key": "x",
                "fallback_to_mock": False,
            })(),
        )
        ctx = ExecContext(
            subject_field="CV",
            degree=Degree.BACHELOR,
            theme="T",
            literature=SAMPLE_POOL,
            outline=json.dumps({"chapters": [
                {"level": 1, "number": "第1章", "title": "绪论"},
                {"level": 1, "number": "第2章", "title": "方法"},
            ]}, ensure_ascii=False),
        )
        ctx.agent_loop_enabled = True
        saved_plans = []
        ctx.agent_plan_callback = saved_plans.append

        result = get_executor(6).execute(ctx)

        assert result.accept is True
        assert client.plan_calls == 3
        assert len(client.chapter_prompts) == 2
        assert "解释研究背景" in client.chapter_prompts[0]
        assert "说明方法设计" in client.chapter_prompts[1]
        assert saved_plans[0]["agent_tool_calls"] == 3
        assert saved_plans[0]["agent_verified_citations"] == ["[L1]", "[L2]"]
        assert result.evidence["agent_loop"] == {
            "enabled": True,
            "turns": 3,
            "tool_calls": 3,
        }

    def test_ring6_agent_rejects_pool_citation_not_checked_by_tool(self, monkeypatch):
        from common.agent_loop import AgentLoopSettings, ModelToolCall, ModelTurn
        from common.llm import StructuredOutputError
        from executor import ring6_chapter as r6

        turns = iter([
            ModelTurn(tool_calls=(ModelToolCall(
                "read-outline",
                "read_approved_context",
                '{"kind":"outline"}',
            ),)),
            ModelTurn(content=json.dumps({
                "chapter_plans": [{
                    "chapter_no": 1,
                    "objectives": ["解释研究背景"],
                    "suggested_refs": ["[L1]"],
                    "evidence_gaps": [],
                }],
                "global_notes": [],
            }, ensure_ascii=False)),
        ])
        client = type("Client", (), {
            "complete_with_tools": staticmethod(lambda *_: next(turns)),
        })()
        monkeypatch.setattr(r6, "get_llm_client", lambda: client)
        ctx = ExecContext(
            subject_field="CV",
            degree=Degree.BACHELOR,
            theme="T",
            literature=SAMPLE_POOL,
            outline=json.dumps({"chapters": [
                {"level": 1, "number": "第1章", "title": "绪论"},
            ]}, ensure_ascii=False),
        )

        with pytest.raises(StructuredOutputError, match="未check_citation核验"):
            r6._build_writing_plan(  # noqa: SLF001 - 针对安全边界的回归测试
                ctx,
                "T",
                [("第1章", "绪论")],
                AgentLoopSettings(max_turns=3),
            )
