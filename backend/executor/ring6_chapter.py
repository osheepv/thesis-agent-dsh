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
import math
import re

from pydantic import BaseModel, ConfigDict, Field

from common.agent_loop import (
    AgentLoopSettings,
    BoundedToolLoop,
    ReadOnlyTool,
    ToolLoopError,
)
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
    used_result_ids: list[str] = Field(default_factory=list, description="实际引用的已核验结果 ID")


class LLMChapterWriteOut(BaseModel):
    """LLM 环6 输出模型（要求严格按此 schema 返回 JSON）。"""

    theme: str = Field(default="", description="题目")
    degree: str = Field(default="", description="学位层次 BACHELOR/MASTER/PHD")
    chapters: list[ChapterDraft] = Field(default_factory=list, description="章节草稿")
    total_words: int = Field(default=0, description="总字数估算")


class ChapterWritingPlan(BaseModel):
    chapter_no: int
    objectives: list[str] = Field(min_length=1, max_length=6)
    suggested_refs: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)


class WritingPlanOut(BaseModel):
    chapter_plans: list[ChapterWritingPlan] = Field(min_length=1)
    global_notes: list[str] = Field(default_factory=list)


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


def _parse_writing_plan(content: str) -> WritingPlanOut:
    """容忍模型在JSON前后添加简短说明，但不放宽结构校验。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        return WritingPlanOut.model_validate_json(cleaned)
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned, index)
            return WritingPlanOut.model_validate(value)
        except Exception:
            continue
    raise StructuredOutputError(
        "环6写作计划JSON无效：无法从模型最终内容解析约定结构"
    )


def _writing_plan_tools(
    ctx: ExecContext,
    chapter_meta: list[tuple[str, str]],
    confirmed_citations: set[str] | None = None,
) -> list[ReadOnlyTool]:
    """把现有文献、知识库和验收逻辑包装成只读工具。"""
    literature = [
        item if isinstance(item, dict) else item.to_dict()
        for item in (ctx.literature or [])
    ]

    def search_sources(arguments: dict) -> dict:
        from common.rag import _keyword_tokens, search_kb_blocks

        query = str(arguments.get("query", "")).strip()
        limit = min(8, max(1, int(arguments.get("limit", 5) or 5)))
        if not query:
            raise ValueError("query不能为空")
        query_terms = set(_keyword_tokens(query))
        ranked = []
        for index, item in enumerate(literature, start=1):
            text = f"{item.get('title', '')} {item.get('abstract', '')}"
            overlap = len(query_terms & set(_keyword_tokens(text)))
            if overlap:
                ranked.append((overlap, index, item))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        references = [
            {
                "marker": f"[L{index}]",
                "title": item.get("title", ""),
                "doi": item.get("doi", ""),
                "reliability": item.get("reliability", ""),
                "abstract": str(item.get("abstract", ""))[:300],
            }
            for _, index, item in ranked[:limit]
        ]
        kb_hits = [
            {
                "file": hit.get("file", ""),
                "text": str(hit.get("text", ""))[:400],
                "score": hit.get("score"),
                "mode": hit.get("retrieval_mode", ""),
            }
            for hit in search_kb_blocks(ctx.session_id, query, k=limit)
        ]
        return {"references": references, "knowledge_blocks": kb_hits}

    def read_approved_context(arguments: dict) -> dict:
        kind = str(arguments.get("kind", "")).strip()
        contexts = {
            "outline": json.loads(ctx.outline or "{}"),
            "results": list(getattr(ctx, "results", []) or []),
            "argument_map": dict(getattr(ctx, "argument_map", {}) or {}),
            "research_protocol": dict(getattr(ctx, "research_protocol", {}) or {}),
        }
        if kind not in contexts:
            raise ValueError(f"不支持的批准上下文: {kind}")
        return {"kind": kind, "data": contexts[kind]}

    def check_citation(arguments: dict) -> dict:
        marker = str(arguments.get("marker", "")).strip()
        match = re.fullmatch(r"\[L(\d+)\]", marker)
        if not match:
            return {"marker": marker, "valid": False, "reason": "格式必须为[L序号]"}
        index = int(match.group(1))
        if index < 1 or index > len(literature):
            return {"marker": marker, "valid": False, "reason": "超出文献池"}
        item = literature[index - 1]
        if confirmed_citations is not None:
            confirmed_citations.add(marker)
        return {
            "marker": marker,
            "valid": True,
            "title": item.get("title", ""),
            "doi": item.get("doi", ""),
            "reliability": item.get("reliability", ""),
        }

    def check_plan_structure(arguments: dict) -> dict:
        chapter_no_list = [
            int(value) for value in (arguments.get("chapter_nos", []) or [])
        ]
        chapter_nos = set(chapter_no_list)
        expected = set(range(1, len(chapter_meta) + 1))
        markers = [str(value) for value in (arguments.get("citations", []) or [])]
        invalid = [
            marker
            for marker in markers
            if not (
                (match := re.fullmatch(r"\[L(\d+)\]", marker))
                and 1 <= int(match.group(1)) <= len(literature)
            )
        ]
        return {
            "complete": (
                chapter_nos == expected
                and len(chapter_no_list) == len(chapter_nos)
                and not invalid
            ),
            "missing_chapters": sorted(expected - chapter_nos),
            "unexpected_chapters": sorted(chapter_nos - expected),
            "duplicate_chapters": sorted({
                number for number in chapter_no_list
                if chapter_no_list.count(number) > 1
            }),
            "invalid_citations": invalid,
        }

    object_schema = {"type": "object", "additionalProperties": False}
    return [
        ReadOnlyTool(
            name="search_sources",
            description="在当前任务已检索文献和项目知识库中搜索写作证据，只读。",
            parameters={
                **object_schema,
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["query"],
            },
            handler=search_sources,
        ),
        ReadOnlyTool(
            name="read_approved_context",
            description="读取已批准的大纲、结果、论证图或研究协议，只读。",
            parameters={
                **object_schema,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["outline", "results", "argument_map", "research_protocol"],
                    }
                },
                "required": ["kind"],
            },
            handler=read_approved_context,
        ),
        ReadOnlyTool(
            name="check_citation",
            description="检查一个[L序号]是否属于当前批准文献池。",
            parameters={
                **object_schema,
                "properties": {"marker": {"type": "string"}},
                "required": ["marker"],
            },
            handler=check_citation,
        ),
        ReadOnlyTool(
            name="check_plan_structure",
            description="检查写作计划是否覆盖全部章节且引用编号有效。",
            parameters={
                **object_schema,
                "properties": {
                    "chapter_nos": {"type": "array", "items": {"type": "integer"}},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["chapter_nos", "citations"],
            },
            handler=check_plan_structure,
        ),
    ]


def _build_writing_plan(
    ctx: ExecContext,
    theme: str,
    chapter_meta: list[tuple[str, str]],
    settings: AgentLoopSettings,
) -> dict:
    chapter_list = [
        {"chapter_no": index, "number": number, "title": title}
        for index, (number, title) in enumerate(chapter_meta, start=1)
    ]
    tpl = prompt_repo.render("ring6_plan", {
        "theme": theme,
        "degree_label": ctx.degree.label,
        "subject_field": ctx.subject_field,
        "chapter_list": json.dumps(chapter_list, ensure_ascii=False),
    })
    loop = BoundedToolLoop(
        get_llm_client().complete_with_tools,
        settings,
    )
    confirmed_citations: set[str] = set()
    try:
        outcome = loop.run(
            system=tpl["system"],
            prompt=tpl["prompt"],
            tools=_writing_plan_tools(ctx, chapter_meta, confirmed_citations),
            require_tool_call=True,
        )
    except ToolLoopError as exc:
        raise StructuredOutputError(f"环6写作计划Agent失败: {exc}") from exc
    plan = _parse_writing_plan(outcome.content)
    expected = set(range(1, len(chapter_meta) + 1))
    chapter_numbers = [item.chapter_no for item in plan.chapter_plans]
    actual = set(chapter_numbers)
    if actual != expected or len(chapter_numbers) != len(expected):
        raise StructuredOutputError(
            f"环6写作计划章节覆盖错误: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}, "
            f"duplicates={sorted({number for number in chapter_numbers if chapter_numbers.count(number) > 1})}"
        )
    suggested_refs = {
        marker
        for item in plan.chapter_plans
        for marker in item.suggested_refs
    }
    invalid_refs = sorted({
        marker
        for marker in suggested_refs
        if not (
            (match := re.fullmatch(r"\[L(\d+)\]", marker))
            and 1 <= int(match.group(1)) <= len(ctx.literature or [])
        )
    })
    if invalid_refs:
        raise StructuredOutputError(f"环6写作计划含池外引用: {invalid_refs}")
    unconfirmed_refs = sorted(suggested_refs - confirmed_citations)
    if unconfirmed_refs:
        raise StructuredOutputError(
            f"环6写作计划含未check_citation核验的引用: {unconfirmed_refs}"
        )
    return {
        **plan.model_dump(),
        "agent_verified_citations": sorted(confirmed_citations),
        "agent_trace": outcome.trace,
        "agent_turns": outcome.turns,
        "agent_tool_calls": outcome.tool_call_count,
    }


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
            if not settings.fallback_to_mock:
                raise LLMError("环6需要可用的 LLM；正式模式禁止静默回退 Mock")
            return self._fallback_mock(ctx, theme)

        evidence = {
            "degree": ctx.degree.value,
            "chapter_count": len(chapter_result.chapters),
            "total_words": chapter_result.total_words,
            "source": source,
            "used_refs": chapter_result.used_refs if source == "deepseek" else [],
            "agent_loop": {
                "enabled": bool(getattr(ctx, "agent_loop_enabled", False)),
                "turns": int((getattr(ctx, "agent_plan_result", {}) or {}).get("agent_turns", 0)),
                "tool_calls": int((getattr(ctx, "agent_plan_result", {}) or {}).get("agent_tool_calls", 0)),
            },
        }

        return ExecResult(
            output=chapter_result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=[],
            evidence=evidence,
        )

    def _llm_generate(self, ctx: ExecContext, theme: str) -> ChapterWriteResult:
        """逐章调用 DeepSeek，避免整篇输出被单次 Token 上限截断。"""
        chapter_meta = _extract_chapters(ctx.outline)
        agent_plan = dict(getattr(ctx, "agent_plan_checkpoint", {}) or {})
        if bool(getattr(ctx, "agent_loop_enabled", False)) and not agent_plan:
            agent_plan = _build_writing_plan(
                ctx,
                theme,
                chapter_meta,
                AgentLoopSettings(),
            )
            plan_callback = getattr(ctx, "agent_plan_callback", None)
            if callable(plan_callback):
                plan_callback(agent_plan)
        ctx.agent_plan_result = agent_plan
        target_per_chapter = math.ceil(
            ctx.degree.min_word_requirement / max(len(chapter_meta), 1)
        )
        target_max_per_chapter = target_per_chapter + max(500, target_per_chapter // 4)
        # 文献池注入（仅可引用池内条目，防止 AI 编造引文）
        pool_block = lit_pool_block(
            [it if isinstance(it, dict) else it.to_dict() for it in ctx.literature]
            if ctx.literature else []
        )
        # RAG：知识库全文语义检索（本地嵌入，零成本；不可用返回空串不阻塞）
        from common.rag import kb_blocks_text

        try:
            kb_block = kb_blocks_text(ctx.session_id, theme, k=6)
        except Exception:  # noqa: BLE001
            kb_block = ""
        if kb_block:
            pool_block = pool_block + "\n" + kb_block
        verified_results = list(getattr(ctx, "results", []) or [])
        result_block = _verified_result_block(verified_results)
        checkpoint = list(getattr(ctx, "chapter_checkpoint", []) or [])
        checkpoint_by_no = {
            chapter.chapter_no: chapter
            for chapter in (ChapterDraft.model_validate(item) for item in checkpoint)
            if 1 <= chapter.chapter_no <= len(chapter_meta)
        }
        chapters: list[ChapterDraft] = []
        enforce_chapter_minimum = bool(
            getattr(ctx, "enforce_chapter_minimum", False)
        )
        checkpoint_callback = getattr(ctx, "chapter_checkpoint_callback", None)
        max_output_tokens = min(
            8192,
            max(4096, math.ceil(target_max_per_chapter * 1.4)),
        )
        for chapter_no, (number, title) in enumerate(chapter_meta, start=1):
            existing = checkpoint_by_no.get(chapter_no)
            if existing is not None and (
                not enforce_chapter_minimum
                or _count_words(existing.content) >= target_per_chapter
            ):
                chapters.append(existing)
                continue
            degree_gen = (
                f"全文最低 {ctx.degree.min_word_requirement} 字；当前仅写第{chapter_no}章，"
                f"该章控制在 {target_per_chapter}~{target_max_per_chapter} 字，"
                "不得用提纲或占位句代替正文，也不要通过重复段落凑字数"
            )
            tpl = prompt_repo.render("ring6_chapter", {
                "theme": theme,
                "subject_field": ctx.subject_field,
                "degree_label": ctx.degree.label,
                "degree_gen": degree_gen,
                "titles_hint": f"{number} {title}",
                "pool_block": pool_block,
                "result_block": result_block,
                "agent_plan_block": (
                    "【已核验写作计划】\n"
                    + json.dumps(
                        next(
                            (
                                item
                                for item in agent_plan.get("chapter_plans", [])
                                if int(item.get("chapter_no", 0) or 0) == chapter_no
                            ),
                            {},
                        ),
                        ensure_ascii=False,
                    )
                    if agent_plan
                    else "【写作计划Agent】本任务未启用。"
                ),
            })
            selected: ChapterDraft | None = None
            correction = ""
            for revision in range(2):
                raw = get_llm_client().generate_json(
                    system=tpl["system"],
                    prompt=tpl["prompt"] + correction,
                    model_cls=LLMChapterWriteOut,
                    temperature=0.35,
                    max_output_tokens=max_output_tokens,
                )
                if not raw.chapters:
                    raise StructuredOutputError(f"第{chapter_no}章返回空章节")
                selected = raw.chapters[0]
                selected.chapter_no = chapter_no
                selected.chapter_title = selected.chapter_title or f"{number} {title}"
                selected.word_count = _count_words(selected.content)
                if not enforce_chapter_minimum or selected.word_count >= target_per_chapter:
                    break
                correction = (
                    "\n【长度纠偏】上一版正文只有 "
                    f"{selected.word_count} 字，低于最低 {target_per_chapter} 字。"
                    "请保留已有事实、引用标记和章节结构，补充分析、方法细节、"
                    "限制条件与小结后，重新输出完整章节JSON。"
                    f"\n【上一版正文】\n{selected.content}"
                )
            if selected is None or (
                enforce_chapter_minimum
                and selected.word_count < target_per_chapter
            ):
                actual = selected.word_count if selected is not None else 0
                raise StructuredOutputError(
                    f"第{chapter_no}章两次生成后仍仅 {actual} 字，"
                    f"低于最低 {target_per_chapter} 字"
                )
            chapters.append(selected)
            checkpoint_by_no[chapter_no] = selected
            if callable(checkpoint_callback):
                checkpoint_callback([
                    checkpoint_by_no[number].model_dump()
                    for number in sorted(checkpoint_by_no)
                ])

        _append_verified_results(chapters, verified_results)
        used_refs: list[str] = []
        used_result_ids: list[str] = []
        for ch in chapters:
            used_refs.extend(re.findall(r"\[L\d+\]", ch.content))
            used_result_ids.extend(re.findall(r"\[(RES-[A-Z0-9]+)\]", ch.content))
        return ChapterWriteResult(
            theme=theme,
            degree=ctx.degree,
            chapters=chapters,
            total_words=sum(_count_words(ch.content) for ch in chapters),
            used_refs=list(dict.fromkeys(used_refs)),
            used_result_ids=list(dict.fromkeys(used_result_ids)),
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
            accept=False,
            fallbackTo=6,
            issues=["真实模型不可用，降级模板稿禁止进入作者审批"],
            evidence={
                "degree": ctx.degree.value,
                "chapter_count": len(drafts),
                "total_words": total_words,
                "paragraphs_per_chapter": _DEGREE_PARAGRAPHS[ctx.degree],
                "source": "mock",
            },
        )


def _verified_result_block(results: list[dict]) -> str:
    if not results:
        return "【已核验实验结果】无。不得编造任何实验数字。"
    lines = ["【已核验实验结果】仅可使用以下结果；正文保留 [RES-*] 标记并定义 BOOKMARK："]
    for item in results:
        result_id = str(item.get("result_id", ""))
        target = str(item.get("table_or_figure_id", "")) or result_id
        lines.append(
            f"- {result_id}: {item.get('metric')}={item.get('value')}{item.get('unit', '')}; "
            f"目标={target}; 来源文件={item.get('source_file_id', '')}; "
            f"复算={item.get('computation', '')}"
        )
    return "\n".join(lines)


def _append_verified_results(chapters: list[ChapterDraft], results: list[dict]) -> None:
    if not chapters or not results:
        return
    target_chapter = next(
        (
            chapter
            for chapter in chapters
            if any(token in chapter.chapter_title for token in ("实验", "结果", "分析", "讨论"))
        ),
        chapters[-1],
    )
    additions: list[str] = []
    for item in results:
        result_id = str(item.get("result_id", ""))
        target = str(item.get("table_or_figure_id", "")) or result_id
        display = target.replace("TABLE-", "表").replace("FIGURE-", "图")
        if f"[{result_id}]" in target_chapter.content:
            continue
        additions.append(
            f"[[BOOKMARK:{target}|{display} {item.get('metric')}结果]]\n"
            f"根据作者批准的结果账本，{item.get('metric')}="
            f"{item.get('value')}{item.get('unit', '')} [{result_id}]。"
            f"该结果来源于文件 {item.get('source_file_id', '')}，"
            f"复算方法为：{item.get('computation', '按结果账本复算')}。"
        )
    if additions:
        target_chapter.content = (
            target_chapter.content.rstrip()
            + "\n\n## 经核验实验结果\n\n"
            + "\n\n".join(additions)
        )
        target_chapter.word_count = _count_words(target_chapter.content)
