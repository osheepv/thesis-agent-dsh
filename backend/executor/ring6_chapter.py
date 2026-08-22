# -*- coding: utf-8 -*-
"""环6 分章撰写执行体（M2 一期，确定性 Mock）。

职责：根据大纲（``ctx.outline`` 或回退到 ``ctx.theme``）逐章节生成初稿，
产出 ``t_chapter_draft`` 风格章节草稿（章节号 / 标题 / 正文 markdown）。

DSH 二期接入点：真实实现应调用 DSH 依大纲逐步生成内容，并写入 t_chapter_draft 表。
本期用模板生成占位章节草稿（Markdown），保证闭环可运行。
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)


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

        evidence = {
            "degree": ctx.degree.value,
            "chapter_count": len(drafts),
            "total_words": total_words,
            "paragraphs_per_chapter": _DEGREE_PARAGRAPHS[ctx.degree],
            "source_mock": "确定性 Mock（DSH 二期接入，t_chapter_draft 落库）",
        }

        return ExecResult(
            output=chapter_result.model_dump_json(indent=2, ensure_ascii=False),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )
