# -*- coding: utf-8 -*-
"""主编排用例（UC-01~UC-04 聚合）。

将「创建论文任务 → 环1选题 → 环5大纲 → 环6撰写 → 生成 docx」串成一个可运行
最小闭环。每个步骤以 `Result[T]` 包裹；错误以 `BizException` 抛出，由上层
（controller / FastAPI handler）统一转换为 `Result.fail`。

模块边界（与 M1 / M2 / M5+M6 成员产物直接对接）：
    - M1 FSM 编排器：直接复用 `fsm.orchestrator.FsmOrchestrator`（状态推进/进度）。
    - M2 执行体：直接复用 `executor.get_executor(ring).execute(ctx)`（四字段结果，
      output 为 JSON 字符串）。
    - M5/M6 docx：经由 :class:`DocxRenderPort` 抽象端口接入，生产实现由
      :class:`RealDocxRenderer` 提供；测试可注入 mock 避免对真实 docxtpl 的依赖。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from common.aicoding.dto.result import Result
from common.aicoding.enums.degree import Degree
from common.aicoding.enums.ring_type import RingType
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode

from executor import ExecContext, get_executor
from fsm.orchestrator import FsmOrchestrator, RING_NO_TO_TYPE
from fsm.repository import InMemoryFsmRepository


# =====================================================================
# Docx 渲染端口（M5/M6 抽象）
# =====================================================================
@runtime_checkable
class DocxRenderPort(Protocol):
    """docx 模板解析与生成端口。"""

    def upload_template(self, file_bytes: bytes, filename: str, **meta: Any) -> Dict[str, Any]:
        """解析模板占位符，返回 {template_id, placeholders, ...}。"""
        ...

    def generate(self, template_id: str, content: Dict[str, Any], **meta: Any) -> Dict[str, Any]:
        """按模板 + 内容生成 docx，返回 {file_id, download_url, ...}。"""
        ...


class RealDocxRenderer:
    """生产实现：包装 M5 parser 与 M6 generator（惰性导入）。

    注意：业务包 `backend.thesis_docx` 已与 pip 的 python-docx 库（顶层名 `docx`）
    解同名。`import docx` 固定解析到 site-packages 的 python-docx 库；业务包
    使用 `backend.thesis_docx` 命名空间导入。本处惰性导入，构造时不触碰业务包，
    仅当真正执行「解析/生成」时才 import；测试注入 mock 时不会触发。
    """

    def __init__(self) -> None:
        self._parser = None
        self._generator = None

    def _ensure(self) -> None:
        if self._parser is not None and self._generator is not None:
            return
        # 业务包 backend.thesis_docx（已与 pip 的 python-docx 库解同名）。
        from thesis_docx.parser.template_parser import TemplateParser
        from thesis_docx.generator.docx_generator import DocxGenerator

        self._parser = TemplateParser()
        self._generator = DocxGenerator()

    def upload_template(self, file_bytes: bytes, filename: str, **meta: Any) -> Dict[str, Any]:
        self._ensure()
        outcome = self._parser.validate_and_parse(file_bytes, filename)
        return {
            "template_id": meta.get("template_id", f"TPL-{uuid.uuid4().hex[:12].upper()}"),
            "filename": filename,
            "placeholders": outcome.placeholders,
            "section_count": len(outcome.skeleton),
        }

    def generate(self, template_id: str, content: Dict[str, Any], **meta: Any) -> Dict[str, Any]:
        self._ensure()
        template_path = meta.get("template_path", "")
        if not template_path:
            # 未提供用户模板时回退到内置论文模板（含标准占位符），兑现
            # 「无模板也能生成」的契约。注意：python-docx 内置 default.docx 是
            # 空模板（无占位符），渲染出来是空壳；这里改用本仓库内置模板。
            from thesis_docx.config import DocxConfig

            template_path = str(DocxConfig.BUILTIN_TEMPLATE_PATH)
            if not os.path.exists(template_path):
                raise BizException(
                    ErrorCode.DOCX_GENERATE_FAILED,
                    msg="生成 docx 需要模板落盘路径（template_path）",
                    detail={"template_id": template_id, "fallback": template_path},
                )
        outcome = self._generator.render(
            template_path=template_path,
            content=content,
            filename=meta.get("filename"),
        )
        return {
            "file_id": f"FILE-{uuid.uuid4().hex[:12].upper()}",
            "download_url": f"/api/v1/docx/files/{outcome.filename}",
            "filename": outcome.filename,
            "word_count": outcome.word_count,
        }


# =====================================================================
# 任务记录（内存态 + 会话隔离预留）
# =====================================================================
class TaskRecord:
    """应用层任务暂存记录。"""

    __slots__ = (
        "task_id", "title", "degree", "subject_field", "template_id",
        "session_id", "tenant_id",
        "ring1", "ring5", "ring6", "docx",
    )

    def __init__(self, task_id: str, title: str, degree: str, subject_field: str,
                 session_id: str = "", tenant_id: str = "default",
                 template_id: Optional[str] = None) -> None:
        self.task_id = task_id
        self.title = title
        self.degree = degree
        self.subject_field = subject_field
        self.template_id = template_id
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.ring1: Optional[Dict[str, Any]] = None
        self.ring5: Optional[Dict[str, Any]] = None
        self.ring6: Optional[Dict[str, Any]] = None
        self.docx: Optional[Dict[str, Any]] = None


class _TaskStore:
    """进程内任务暂存（线程安全）。"""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    def put(self, rec: TaskRecord) -> TaskRecord:
        with self._lock:
            self._tasks[rec.task_id] = rec
        return rec

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)


# =====================================================================
# 主编排用例
# =====================================================================
class MainOrchestration:
    """主编排用例。

    Args:
        fsm: M1 FSM 编排器（默认注入内存仓储的 FsmOrchestrator）。
        docx_renderer: M5/M6 docx 渲染端口（默认 RealDocxRenderer）。
        store: 任务暂存（默认进程内实例）。
    """

    def __init__(
        self,
        fsm: Optional[FsmOrchestrator] = None,
        docx_renderer: Optional[DocxRenderPort] = None,
        store: Optional[_TaskStore] = None,
    ) -> None:
        self._fsm = fsm or FsmOrchestrator(InMemoryFsmRepository())
        self._docx = docx_renderer or RealDocxRenderer()
        self._store = store or _TaskStore()

    # ------------------------------------------------------------------
    # 步骤 1：创建论文任务（UC-01）
    # ------------------------------------------------------------------
    def create_task(self, title: str, degree: Degree, subject_field: str,
                    template_id: Optional[str] = None, session_id: str = "",
                    tenant_id: str = "default") -> Result[Dict[str, Any]]:
        """创建论文任务并初始化 FSM（默认停在环1）。

        Returns:
            含 task_id / title / degree / subject_field / current_ring 的任务视图。
        """
        try:
            state = self._fsm.create_task(
                title=title, degree=degree, subject_field=subject_field,
                template_id=template_id or "",
            )
            rec = TaskRecord(
                task_id=state.task_id, title=title, degree=degree.value,
                subject_field=subject_field, session_id=session_id,
                tenant_id=tenant_id, template_id=template_id,
            )
            self._store.put(rec)
            data = {
                "task_id": state.task_id,
                "title": title,
                "degree": degree.value,
                "subject_field": subject_field,
                "template_id": template_id,
                "current_ring": state.ring.value,
                "status": "NOT_STARTED",
            }
            return Result.ok(data=data, msg="论文任务创建成功", trace_id=session_id, tenant_id=tenant_id)
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.TASK_STATE_INVALID, msg=f"创建论文任务失败: {exc}", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # 步骤 2：解析模板占位符（UC-01b，可选）
    # ------------------------------------------------------------------
    def upload_template(self, task_id: str, file_bytes: bytes, filename: str,
                        session_id: str = "") -> Result[Dict[str, Any]]:
        """解析已上传模板的占位符，返回模板信息（可选步骤）。"""
        rec = self._require(task_id)
        try:
            info = self._docx.upload_template(
                file_bytes, filename, template_id=f"TPL-{uuid.uuid4().hex[:12].upper()}",
                task_id=task_id, session_id=session_id,
            )
            rec.template_id = info.get("template_id")
            return Result.ok(data=info, msg="模板解析成功")
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.DOCX_PARSE_FAILED, msg=f"模板解析失败: {exc}", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # 步骤 3：环1 选题（UC-02）
    # ------------------------------------------------------------------
    def run_ring1(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环1选题：M2 产出候选题目，并推进 FSM 到环2。"""
        rec = self._require(task_id)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(1).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环1选题未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        data = json.loads(res.output)
        candidates = data.get("candidates", [])
        chosen_title = candidates[0]["title"] if candidates else data.get("theme", rec.title)
        rec.ring1 = {"candidates": candidates, "chosen": chosen_title}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R1", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R1", target_ring_no=2)
        return Result.ok(data={"candidates": candidates, "chosen": chosen_title,
                               "recommendation": data.get("recommendation", "")},
                         msg="环1选题完成")

    # ------------------------------------------------------------------
    # 步骤 4：环5 大纲（UC-03）
    # ------------------------------------------------------------------
    def run_ring5(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环5大纲：基于选题生成章节结构，并推进 FSM。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(5).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环5大纲未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        outline = json.loads(res.output)
        chapters = outline.get("chapters", [])
        outline_text = self._outline_to_text(chapters)
        rec.ring5 = {"outline": outline_text, "chapters": outline.get("chapters", []),
                     "theme": outline.get("theme", chosen)}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R5", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R5", target_ring_no=6)
        return Result.ok(data={"outline": outline_text, "chapters": chapters,
                               "summary": outline.get("summary", "")}, msg="环5大纲完成")

    # ------------------------------------------------------------------
    # 步骤 5：环6 撰写（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring6(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环6撰写：基于大纲生成初稿正文，并推进 FSM。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        outline_text = (rec.ring5 or {}).get("outline", "")
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            outline=outline_text,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(6).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环6初稿未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        draft = json.loads(res.output)
        chapters = draft.get("chapters", [])
        full_content = self._draft_to_text(chapters)
        rec.ring6 = {"chapters": chapters, "content": full_content,
                     "total_words": draft.get("total_words", 0)}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R6", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R6", target_ring_no=7)
        return Result.ok(data={"chapters": chapters, "total_words": draft.get("total_words", 0),
                               "content_preview": full_content[:200]}, msg="环6撰写完成")

    # ------------------------------------------------------------------
    # 步骤 6：生成 docx（UC-04）
    # ------------------------------------------------------------------
    def generate_docx(self, task_id: str, template_id: Optional[str] = None) -> Result[Dict[str, Any]]:
        """按用户模板 + 初稿内容生成 docx，返回下载链接。

        若未提供真实模板，则回退到内置骨架渲染（依据大纲+正文标记生成占位语法，
        由渲染端替换；测试注入 mock 时直接返回假链接）。
        """
        rec = self._require(task_id)
        tid = template_id or rec.template_id
        content = {
            "topic": rec.title,
            "title": rec.title,
            "outline": (rec.ring5 or {}).get("outline", ""),
            "chapter": (rec.ring6 or {}).get("content", ""),
            "content": (rec.ring6 or {}).get("content", ""),
            "degree": rec.degree,
            "subject_field": rec.subject_field,
        }
        try:
            gen = self._docx.generate(tid, content=content, task_id=task_id)
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED, msg=f"docx 生成失败: {exc}", detail=str(exc)
            ) from exc
        rec.docx = {"file_id": gen.get("file_id"), "download_url": gen.get("download_url"),
                    "filename": gen.get("filename", "")}
        return Result.ok(data=gen, msg="docx 生成完成")

    # ------------------------------------------------------------------
    # 进度视图
    # ------------------------------------------------------------------
    def progress(self, task_id: str) -> Result[Dict[str, Any]]:
        """读取任务进度（委托 M1 FSM progress）。"""
        try:
            return Result.ok(data=self._fsm.get_progress(task_id), msg="进度查询成功")
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.STATE_READ_FAILED, msg=f"进度查询失败: {exc}", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # 会话隔离校验
    # ------------------------------------------------------------------
    def assert_session(self, task_id: str, session_id: str) -> None:
        """校验任务归属指定会话（M9 会话隔离预留）。

        Args:
            task_id: 任务 ID。
            session_id: 请求携带的会话 ID。空串表示默认会话，允许访问。
        Raises:
            BizException: 任务不存在或不属于该会话。
        """
        rec = self._require(task_id)
        if session_id and rec.session_id and rec.session_id != session_id:
            raise BizException(
                ErrorCode.FORBIDDEN, msg="任务不属于当前会话，禁止访问",
                detail={"task_id": task_id, "session_id": session_id},
            )

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _require(self, task_id: str) -> TaskRecord:
        rec = self._store.get(task_id)
        if rec is None:
            raise BizException(ErrorCode.TASK_NOT_FOUND, msg=f"任务不存在: {task_id}")
        return rec

    def _advance_to(self, task_id: str, biz_req_no: str, target_ring_no: int) -> None:
        """把 FSM 推进到目标环节号（含跨过 HITL 敏感环节）。

        闭环仅覆盖环1/环5/环6 三个执行环节，环2/4/8/10 为 HITL 通过式网关，
        advance 每次恰好 +1 环且落在 HITL 环节时置 IN_PROGRESS 等待人工确认。
        执行体验收通过后，这里自动确认途经的 HITL 网关（环2/4/8/10），直至到达
        目标环节：run_ring1 → 停在环2、run_ring5 → 环6、run_ring6 → 环7。

        Args:
            task_id: 任务 ID。
            biz_req_no: 推进幂等键前缀（实际透传，避免重复推进）。
            target_ring_no: 目标环节号（2/6/7），到达后停止，不再继续推进。
        """
        state = self._fsm.get_task(task_id)
        while state.current_ring_no < target_ring_no:
            ring = RING_NO_TO_TYPE[state.current_ring_no]
            if ring.is_hitl_gate:
                state = self._fsm.confirm_hitl(task_id, confirmed=True)
            else:
                state = self._fsm.advance(
                    task_id=task_id, biz_req_no=f"{biz_req_no}-to-{state.current_ring_no}",
                    accept=True,
                )

    @staticmethod
    def _outline_to_text(chapters: List[Dict[str, Any]]) -> str:
        """把大纲节点平铺为可读文本（供环6/渲染端消费）。"""
        lines: List[str] = []
        for node in chapters:
            if not isinstance(node, dict):
                continue
            level = node.get("level", 1)
            number = node.get("number", "")
            title = node.get("title", "")
            prefix = "  " * (level - 1)
            lines.append(f"{prefix}{number} {title}".strip())
        return "\n".join(lines)

    @staticmethod
    def _draft_to_text(chapters: List[Dict[str, Any]]) -> str:
        """把各章节草稿拼接为完整正文文本。"""
        parts: List[str] = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            title = ch.get("chapter_title", "")
            content = ch.get("content", "")
            parts.append(f"# {title}\n\n{content}".strip())
        return "\n\n".join(parts)
