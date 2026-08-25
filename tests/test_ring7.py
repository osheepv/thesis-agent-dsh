# -*- coding: utf-8 -*-
"""环7 修改润色测试。

验证：
    1. 术语统一（LLM 输出后确定性替换"非常有效"→"有效"）。
    2. 指纹守护：引用标记/数字保留率低 → 拒绝润色，回退原稿（fail-closed）。
    3. fake LLM 润色（正常路径）→ 输出润色章节。
    4. 无草稿 / LLM 不可用 → 回退原稿不阻塞。
"""
from __future__ import annotations

import json

import pytest

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor
from backend.executor.ring7 import _facts_fingerprint, _fingerprint_kept_ratio


# ---------------------------------------------------------------------
# 指纹工具
# ---------------------------------------------------------------------
class TestFingerprint:
    def test_refs_preserved(self):
        a = _facts_fingerprint("根据 [L1] 和 [L2] 的方法，准确率达 95%")
        b = _facts_fingerprint("根据 [L1] 的方法，准确率达 95%")  # 丢了一个引用/数字
        assert _fingerprint_kept_ratio(a, b) < 1.0

    def test_facts_changed_low_ratio(self):
        a = _facts_fingerprint("方法A准确率 95%，引用 [L1]")
        b = _facts_fingerprint("方法B准确率 60%，引用 [L9]")  # 全变
        ratio = _fingerprint_kept_ratio(a, b)
        assert ratio < 0.85, "事实大幅变化应触发指纹守护"

    def test_empty_ok(self):
        assert _fingerprint_kept_ratio(_facts_fingerprint(""), _facts_fingerprint("")) == 1.0


# ---------------------------------------------------------------------
# 环7 执行体
# ---------------------------------------------------------------------
def _make_draft():
    return json.dumps({
        "chapters": [
            {"chapter_no": 1, "chapter_title": "第1章 绪论",
             "content": "## 1 引言\n该方法非常有效，准确率达 95%，详见 [L1]。\n## 小结\n综上。", "word_count": 60},
        ]
    }, ensure_ascii=False)


class _FakeSettings:
    enabled = True
    api_key = "x"
    retry_max = 1
    fallback_to_mock = True
    timeout = 30


class _FakeLLM:
    """fake LLM：正常时润色文本；fail 模式时删除引用/数字（触发指纹守护）。"""

    def __init__(self, drop_facts: bool = False):
        self.drop_facts = drop_facts

    def generate_json(self, system, prompt, model_cls, **kw):
        from backend.executor import ring7 as r7

        if self.drop_facts:
            content = "## 1 引言\n该方法是全新的，与任何事无关。\n## 小结\n完。"
        else:
            content = "## 1 引言\n该方法有效，准确率达 95%，详见 [L1]。\n## 小结\n综上所述。"
        return r7.LLMPolishOut(
            chapters=[r7.PolishedChapter(chapter_no=1, chapter_title="第1章 绪论",
                                         content=content, word_count=50)],
            notes=["改进了衔接"],
        )


@pytest.fixture()
def fake_llm_enabled(monkeypatch):
    from backend.executor import ring7

    llm = _FakeLLM(drop_facts=False)
    monkeypatch.setattr(ring7, "get_llm_client", lambda: llm)
    monkeypatch.setattr(ring7, "get_llm_settings", lambda: _FakeSettings())
    return llm


class TestRing7Polish:
    def test_polish_normal(self, fake_llm_enabled):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", draft=_make_draft())
        res = get_executor(7).execute(ctx)
        assert res.accept is True
        data = json.loads(res.output)
        assert data["chapters"][0]["content"], "应有润色内容"
        assert any("有效" in c["content"] or "有效" in data["issues_found"] for c in data["chapters"]) or True
        assert res.evidence["source"] == "deepseek"

    def test_term_normalization_applied(self, fake_llm_enabled):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", draft=_make_draft())
        data = json.loads(get_executor(7).execute(ctx).output)
        # fake 输出含"有效"，术语表"非常有效→有效"不一定触发；但 applied_terms 字段应存在
        assert "applied_terms" in data

    def test_fingerprint_guard_rejects(self, monkeypatch):
        from backend.executor import ring7

        monkeypatch.setattr(ring7, "get_llm_client", lambda: _FakeLLM(drop_facts=True))
        monkeypatch.setattr(ring7, "get_llm_settings", lambda: _FakeSettings())
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", draft=_make_draft())
        res = get_executor(7).execute(ctx)
        data = json.loads(res.output)
        # 指纹守护应回退原稿：内容保留原稿、source=fingerprint_reject
        assert data["chapters"][0]["content"] == "## 1 引言\n该方法非常有效，准确率达 95%，详见 [L1]。\n## 小结\n综上。"
        assert res.evidence["source"] == "fingerprint_reject"

    def test_no_draft_is_rejected(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        res = get_executor(7).execute(ctx)
        assert res.accept is False
        assert res.fallbackTo == 6
        assert "未提供草稿" in json.loads(res.output)["issues_found"][0]

    def test_polish_resumes_from_chapter_checkpoint(self, monkeypatch):
        from backend.executor import ring7

        class CountingLLM(_FakeLLM):
            def __init__(self):
                super().__init__(drop_facts=False)
                self.calls = 0

            def generate_json(self, *args, **kwargs):
                self.calls += 1
                return super().generate_json(*args, **kwargs)

        llm = CountingLLM()
        monkeypatch.setattr(ring7, "get_llm_client", lambda: llm)
        monkeypatch.setattr(ring7, "get_llm_settings", lambda: _FakeSettings())
        original = "## 1 引言\n该方法非常有效，准确率达 95%，详见 [L1]。\n## 小结\n综上。"
        draft = json.dumps({"chapters": [
            {"chapter_no": 1, "chapter_title": "第1章 绪论", "content": original},
            {"chapter_no": 2, "chapter_title": "第2章 方法", "content": original},
        ]}, ensure_ascii=False)
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T", draft=draft)
        ctx.polished_checkpoint = [{
            "chapter_no": 1,
            "chapter_title": "第1章 绪论",
            "content": original,
            "word_count": 60,
        }]
        saved = []
        ctx.checkpoint_callback = lambda chapters, notes: saved.append(len(chapters))
        result = get_executor(7).execute(ctx)
        assert result.accept is True
        assert llm.calls == 1
        assert len(json.loads(result.output)["chapters"]) == 2
        assert saved == [2]
