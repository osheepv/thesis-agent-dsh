# -*- coding: utf-8 -*-
"""环6 分章撰写执行体（M2 二期：LLM 优先 + Mock 回退）。

职责：根据大纲（``ctx.outline`` 或回退到 ``ctx.theme``）逐章节生成初稿，
产出 ``t_chapter_draft`` 风格章节草稿（章节号 / 标题 / 正文 markdown）。

LLM 接入（决策 D1）：
    优先调用 DeepSeek 按大纲逐章生成；失败时按 ``LLMSettings.fallback_to_mock``
    决定回退确定性 Mock 或抛错。
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.lit import lit_pool_block
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring6")


class ChapterDraft(BaseModel):
    """单章节草稿（对齐 t_chapter_draft 风格）。

    Attributes:
        chapter_no: 章节号，如 1。
        chapter_title: 章节标题，如 第1章 绪论。
        content: 正文（Markdown）。
        word_count: 正文字数估算。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chapter_no: int = Field(default=1, description="章节号")
    chapter_title: str = Field(default="", description="章节标题")
    content: str = Field(default="", description="正文 Markdown")
    word_count: int = Field(default=0, description="正文字数估算")


class ChapterWriteResult(BaseModel):
    """环6 分章撰写执行体结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    theme: str = Field(default="", description="题目")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    chapters: list[ChapterDraft] = Field(default_factory=list, description="章节草稿列表")
    total_words: int = Field(default=0, description="总字数估算")
    used_refs: list[str] = Field(default_factory=list, description="实际引用的文献池编号 [L1] 等")


class LLMChapterWriteOut(BaseModel):
    """LLM 环6 输出模型（要求严格按此 schema 返回 JSON）。"""

    theme: str = Field(default="", description="题目")
    degree: str = Field(default="", description="学位层次 BACHELOR/MASTER/PHD")
    chapters: list[ChapterDraft] = Field(default_factory=list, description="章节草稿")
    total_words: int = Field(default=0, description="总字数估算")


#: 学位差异化的每章正文基准段落数（本科少、博士深）。
_DEGREE_PARAGRAPHS: dict[Degree, int] = {
    Degree.BACHELOR: 2,
    Degree.MASTER: 3,
    Degree.PHD: 5,
}

#: 章号 -> 章节标题 模板（与环5大纲章节骨架对齐）。
_CHAPTER_TITLES: dict[int, str] = {
    1: "绪论",
    2: "相关理论与技术基础",
    3: "系统设计与实现",
    4: "实验与结果分析",
    5: "总结与展望",
}


def _extract_chapters(outline: str) -> list[tuple[str, str]]:
    """从环5大纲 JSON 中解析 (章节号, 章节标题)，失败则回退到默认骨架。

    容错设计：环6 不强制依赖环5的精确格式，取不到就用 _CHAPTER_TITLES。
    """
    result: list[tuple[str, str]] = []
    try:
        data = json.loads(outline)
        chapters_raw = data.get("chapters", [])
        for node in chapters_raw:
            if node.get("level") == 1:
                result.append((node.get("number", ""), node.get("title", "")))
        if result:
            return result
    except Exception:  # noqa: BLE001 - Mock 容错
        pass
    # 回退默认骨架
    return [(f"第{n}章", _CHAPTER_TITLES.get(n, f"第{n}章")) for n in range(1, 6)]


def _strip_title(title: str) -> str:
    """去掉 '第N章' 前缀得到纯净标题。"""
    return re.sub(r"^第[一二三四五六七八九十0-9]+章\s*", "", title).strip()


def _render_chapter_content(chapter_no: int, title: str, degree: Degree) -> str:
    """按段落基准数渲染一章 Markdown 正文（确定性模板）。"""
    paras = _DEGREE_PARAGRAPHS[degree]
    clean_title = _strip_title(title) or f"第{chapter_no}章"
    body: list[str] = []
    body.append("## 1 引言")
    body.append(f"本章围绕「{clean_title}」展开论述，结合领域背景与既有工作，"
                f"明确本章要解决的核心问题与总体思路。")
    for i in range(2, paras + 1):
        body.append(f"## {i} {clean_title}中的关键环节")
        body.append(f"本节梳理第 {i} 个关键环节的主要内容，说明其方法依据、"
                    f"实现路径与对整体目标的支撑作用。")
    body.append("## 小结")
    body.append(f"本章对「{clean_title}」相关要点做了系统梳理，为后续章节奠定基础。")
    return "\n\n".join(body)


def _count_words(text: str) -> int:
    """粗略估算字数（去掉空白后统计可见字符数）。"""
    return len(re.sub(r"[\s#*`-]+", "", text))


@register_executor
class Ring6ChapterExecutor(RingExecutor):
    """环6 分章撰写执行体。"""

    ring_type: RingType = RingType.RING_6
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        theme = ctx.theme.strip() or f"基于{ctx.subject_field}的研究"

        # LLM 优先；失败按配置回退 Mock 或报错
        settings = get_llm_settings()
        if settings.enabled and settings.api_key:
            try:
                chapter_result = self._llm_generate(ctx, theme)
                source = "deepseek"
                if not chapter_result.chapters:
                    raise StructuredOutputError("LLM 返回空章节")
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环6 LLM 不可用，回退 Mock：%s", exc)
                    return self._fallback_mock(ctx, theme)
                raise
        else:
            return self._fallback_mock(ctx, theme)

        evidence = {
            "degree": ctx.degree.value,
            "chapter_count": len(chapter_result.chapters),
            "total_words": chapter_result.total_words,
            "source": source,
            "used_refs": chapter_result.used_refs if source == "deepseek" else [],
        }

        return ExecResult(
            output=chapter_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )

    def _llm_generate(self, ctx: ExecContext, theme: str) -> ChapterWriteResult:
        """调用 DeepSeek 生成章节草稿（LLM 分支）。"""
        degree_gen = {
            Degree.BACHELOR: "本科：每章 2~3 段（约 0.8k 字/章）",
            Degree.MASTER: "硕士：每章 3~4 段（约 1.5k 字/章）",
            Degree.PHD: "博士：每章 5~6 段（约 2.5k 字/章）",
        }[ctx.degree]
        # 从 outline（JSON 或文本）提取章节标题，供 LLM 逐章生成
        chapter_titles: list[str] = []
        try:
            outline_data = json.loads(ctx.outline) if ctx.outline else {}
            for node in outline_data.get("chapters", []):
                if node.get("level") == 1:
                    chapter_titles.append(node.get("title", ""))
        except Exception:  # noqa: BLE001 - 容错，outline 可能为纯文本
            pass
        titles_hint = "；".join(f"{i + 1}.{t}" for i, t in enumerate(chapter_titles)) if chapter_titles else (
            f"参照{ctx.degree.label}论文常规结构"
        )
        # 文献池注入（仅可引用池内条目，防止 AI 编造引文）
        pool_block = lit_pool_block(
            [it if isinstance(it, dict) else it.to_dict() for it in ctx.literature]
            if ctx.literature else []
        )
        tpl = prompt_repo.render("ring6_chapter", {
            "theme": theme,
            "subject_field": ctx.subject_field,
            "degree_label": ctx.degree.label,
            "degree_gen": degree_gen,
            "titles_hint": titles_hint,
            "pool_block": pool_block,
        })
        raw = get_llm_client().generate_json(
            system=tpl["system"],
            prompt=tpl["prompt"],
            model_cls=LLMChapterWriteOut,
        )
        # 从正文提取实际引用的文献池编号 [L1] 等（用于审计/后续引文生成）
        used_refs: list[str] = []
        for ch in raw.chapters:
            used_refs.extend(re.findall(r"\[L\d+\]", ch.content))
        return ChapterWriteResult(
            theme=raw.theme or theme,
            degree=ctx.degree,
            chapters=raw.chapters,
            total_words=raw.total_words or sum(c.word_count for c in raw.chapters),
            used_refs=used_refs,
        )

    def _fallback_mock(self, ctx: ExecContext, theme: str) -> ExecResult:
        """确定性 Mock 回退：按段落基准数逐章生成模板文本。"""
        chapters_meta = _extract_chapters(ctx.outline)
        drafts: list[ChapterDraft] = []
        for chapter_no, (num, raw_title) in enumerate(chapters_meta, start=1):
            content = _render_chapter_content(chapter_no, raw_title, ctx.degree)
            drafts.append(
                ChapterDraft(
                    chapter_no=chapter_no,
                    chapter_title=raw_title,
                    content=content,
                    word_count=_count_words(content),
                )
            )
        total_words = sum(d.word_count for d in drafts)
        chapter_result = ChapterWriteResult(
            theme=theme,
            degree=ctx.degree,
            chapters=drafts,
            total_words=total_words,
        )
        return ExecResult(
            output=chapter_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence={
                "degree": ctx.degree.value,
                "chapter_count": len(drafts),
                "total_words": total_words,
                "paragraphs_per_chapter": _DEGREE_PARAGRAPHS[ctx.degree],
                "source": "mock",
            },
        )
