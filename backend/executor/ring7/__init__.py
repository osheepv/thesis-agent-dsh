# -*- coding: utf-8 -*-
"""环7 修改润色执行体（M2 二期：LLM 润色 + 术语统一 + 指纹守护）。

职责：对环6 初稿进行内容打磨（逻辑/语言/结构）与形式统一（术语/表达），
**只改表达不改事实**（对齐规范环7：逻辑通顺、段落衔接、术语统一、客观表达）。

设计要点：
    1. LLM 润色：注入全文 + 术语表（领域术语统一）+ 引用标记（[L序号] 原样保留）。
    2. 内容指纹守护（借鉴 paper_format_agent fail-closed）：
       润色前后对原文提取『事实指纹』——[L序号] 引用集 + 数字 token + 句首主体词；
       指纹丢失率超阈值 → 判定润色改动了事实，拒绝（fallback 原稿）。
    3. 术语统一：预置术语表（规范用词 → 规范值），LLM 输出后再做确定性替换兜底。
    4. 失败/离线：回退原稿（accept=True），不阻塞闭环。

注意：环7 自动执行（非 HITL），M7 万方查重为环10 定稿的检查项，此处不做查重。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring7")

#: 事实指纹阈值：润色后保留率低于此值视为"改动事实"，拒绝
_FINGERPRINT_MIN_RATIO = 0.85

#: 术语表（规范用词 → 规范值；LLM 输出后确定性替换兜底）
_TERMS: list[tuple[str, str]] = [
    ("深度学习模型", "深度学习模型"),
    ("人工智能", "人工智能"),
    ("很大的提升", "显著提升"),
    ("非常有效", "有效"),
    ("效果非常好", "效果良好"),
    ("基本可以说", "可以认为"),
    ("众所周知", "已有研究指出"),
]


class PolishedChapter(BaseModel):
    """润色后单章节。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chapter_no: int = Field(default=1, description="章节号")
    chapter_title: str = Field(default="", description="标题")
    content: str = Field(default="", description="润色后正文 Markdown")
    word_count: int = Field(default=0, description="字数")


class PolishResult(BaseModel):
    """环7 润色结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    theme: str = Field(default="", description="题目")
    chapters: list[PolishedChapter] = Field(default_factory=list, description="润色后章节")
    total_words: int = Field(default=0, description="总字数")
    issues_found: list[str] = Field(default_factory=list, description="发现的表达问题")
    applied_terms: list[str] = Field(default_factory=list, description="实际应用的术语统一项")


class LLMPolishOut(BaseModel):
    """LLM 润色输出模型。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chapters: list[PolishedChapter] = Field(default_factory=list, description="润色后章节")
    notes: list[str] = Field(default_factory=list, description="润色说明（改了什么）")


def _extract_draft_chapters(ctx: ExecContext) -> list[Dict[str, Any]]:
    """从 ctx.draft（环6 产物 JSON）提取章节。

    Returns:
        [{chapter_no, chapter_title, content}]
    """
    draft = getattr(ctx, "draft", "") or ""
    if not draft:
        return []
    try:
        data = json.loads(draft)
        return data.get("chapters", [])
    except Exception:  # noqa: BLE001
        # 纯文本兜底：整段作为一章
        return [{"chapter_no": 1, "chapter_title": "未分章", "content": draft}]


def _facts_fingerprint(text: str) -> Dict[str, Any]:
    """提取文本『事实指纹』：引用集 + 数字 token + 主体词（用于比对润色前后）。"""
    refs = re.findall(r"\[(?:L\d+|EVD-[A-Z0-9]+|RES-[A-Z0-9]+)\]", text)
    refs.extend(re.findall(r"\[\[(?:BOOKMARK|REF):[^\]]+\]\]", text))
    numbers = re.findall(r"\d+(?:\.\d+)?%?", text)
    # 主体词：含"研究/方法/模型/数据/实验"等的短词（粗略）
    subjects = re.findall(r"[一-鿿A-Za-z]{2,12}(?:研究|方法|模型|数据|实验|算法|系统|框架)", text)
    return {
        "refs": set(refs),
        "numbers": set(numbers),
        "subjects": set(subjects[:20]),  # 截断防噪声
    }


def _fingerprint_kept_ratio(before: Dict[str, Any], after: Dict[str, Any]) -> float:
    """指纹保留率（after 相对 before）。"""
    if not before["refs"] and not before["numbers"]:
        # 无引用无数字：靠主体词粗判（弱保护）
        if not before["subjects"]:
            return 1.0
        a = before["subjects"]
        b = after["subjects"]
        kept = len(a & b) / max(len(a), 1)
        return kept
    parts: List[float] = []

    refs_ratio = len(before["refs"] & after["refs"]) / max(len(before["refs"]), 1) if before["refs"] else 1.0
    nums_ratio = len(before["numbers"] & after["numbers"]) / max(len(before["numbers"]), 1) if before["numbers"] else 1.0
    parts += [refs_ratio, nums_ratio]
    if before["subjects"]:
        parts.append(len(before["subjects"] & after["subjects"]) / max(len(before["subjects"]), 1))
    return sum(parts) / len(parts)


def _term_fix(text: str) -> tuple[str, list[str]]:
    """确定性术语替换（兜底），返回 (文本, 应用项)。"""
    applied = []
    for bad, good in _TERMS:
        if bad in text and bad != good:
            text = text.replace(bad, good)
            applied.append(f"{bad}→{good}")
    return text, applied


@register_executor
class Ring7PolishExecutor(RingExecutor):
    """环7 修改润色执行体。

    输入：ctx.draft（环6 章节草稿 JSON）。
    输出：润色后章节 + 术语统一 + 指纹守护结果。
    """

    ring_type: RingType = RingType.RING_7
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        src_chapters = _extract_draft_chapters(ctx)
        if not src_chapters:
            return ExecResult(
                output=PolishResult(
                    theme=getattr(ctx, "theme", ""),
                    issues_found=["未提供草稿（draft 为空），跳过润色"],
                ).model_dump_json(indent=2),
                accept=True,
                fallbackTo=None,
                issues=["未提供草稿，无内容可润色"],
                evidence={"polished": 0, "source": "none"},
            )

        # 原文指纹（用于 LLM 输出比对）
        src_text = "\n".join(ch.get("content", "") for ch in src_chapters)
        src_fp = _facts_fingerprint(src_text)

        settings = get_llm_settings()
        polished = None
        source = "mock"
        if settings.enabled and settings.api_key:
            try:
                polished = self._llm_polish(ctx, src_chapters)
                source = "deepseek"
            except (LLMError, StructuredOutputError) as exc:
                if settings.fallback_to_mock:
                    logger.warning("环7 LLM 不可用，回退原稿：%s", exc)
                else:
                    raise

        if polished is not None:
            out_text = "\n".join(c.content for c in polished.chapters)
            ratio = _fingerprint_kept_ratio(src_fp, _facts_fingerprint(out_text))
            if ratio < _FINGERPRINT_MIN_RATIO:
                # 指纹守护：润色改动事实 → 拒绝，保留原稿
                logger.warning("环7 指纹守护触发（保留率 %.2f），拒绝润色结果，回退原稿", ratio)
                return self._fallback_original(
                    src_chapters,
                    issue=f"润色疑似改动事实（指纹保留率 {ratio:.2f} < {_FINGERPRINT_MIN_RATIO}），已回退原稿",
                    source="fingerprint_reject",
                )
            # 术语确定性兜底
            fixed_chapters = []
            applied_terms = []
            for ch in polished.chapters:
                fixed, applied = _term_fix(ch.content)
                applied_terms.extend(applied)
                fixed_chapters.append(
                    PolishedChapter(
                        chapter_no=ch.chapter_no,
                        chapter_title=ch.chapter_title,
                        content=fixed,
                        word_count=len(re.sub(r"[\s#*`-]+", "", fixed)),
                    )
                )
            total_words = sum(c.word_count for c in fixed_chapters)
            result = PolishResult(
                theme=getattr(ctx, "theme", ""),
                chapters=fixed_chapters,
                total_words=total_words,
                issues_found=polished.notes,
                applied_terms=list(dict.fromkeys(applied_terms)),
            )
            return ExecResult(
                output=result.model_dump_json(indent=2),
                accept=True,
                fallbackTo=None,
                issues=[],
                evidence={
                    "polished": len(fixed_chapters),
                    "total_words": total_words,
                    "source": source,
                    "fingerprint_ratio": round(ratio, 3),
                    "applied_terms": applied_terms,
                },
            )

        # 离线演示可显式保留原稿；正式模式必须暴露 LLM 不可用。
        if not settings.fallback_to_mock:
            raise LLMError("环7需要可用的 LLM；正式模式禁止静默回退原稿")
        return self._fallback_original(src_chapters, issue="LLM 不可用，保留原稿", source="mock")

    def _llm_polish(self, ctx: ExecContext, src_chapters: List[Dict[str, Any]]) -> LLMPolishOut:
        """LLM 润色分支。"""
        chapters_text = "\n\n".join(
            f"### {ch.get('chapter_title', ch.get('chapter_no', ''))}\n{ch.get('content', '')}"
            for ch in src_chapters
        )
        term_hint = "；".join(f"{b}→{g}" for b, g in _TERMS)
        tpl = prompt_repo.render("ring7_polish", {
            "theme": getattr(ctx, "theme", ""),
            "degree_label": ctx.degree.label,
            "term_hint": term_hint,
            "chapters_text": chapters_text,
        })
        raw = get_llm_client().generate_json(
            system=tpl["system"],
            prompt=tpl["prompt"],
            model_cls=LLMPolishOut,
        )
        return raw

    @staticmethod
    def _fallback_original(src_chapters: List[Dict[str, Any]], issue: str, source: str) -> ExecResult:
        """回退原稿（未润色直接返回），算通过。"""
        chapters = [
            PolishedChapter(
                chapter_no=ch.get("chapter_no", i + 1),
                chapter_title=ch.get("chapter_title", ""),
                content=ch.get("content", ""),
                word_count=len(re.sub(r"[\s#*`-]+", "", ch.get("content", ""))),
            )
            for i, ch in enumerate(src_chapters)
        ]
        total = sum(c.word_count for c in chapters)
        result = PolishResult(
            chapters=chapters,
            total_words=total,
            issues_found=[issue],
        )
        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence={"polished": len(chapters), "source": source, "note": issue},
        )
