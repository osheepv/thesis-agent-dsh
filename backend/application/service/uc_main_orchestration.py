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
import logging
import os
import re
import threading
import uuid

logger = logging.getLogger("thesis.uc")
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

    Args:
        repository: 可选，M6 DocxRepository。提供时生成成功后注册记录，
            供 `/api/v1/docx/files/{file_id}` 下载端点查询（与业务路由共享）。
    """

    def __init__(self, repository=None) -> None:
        self._parser = None
        self._generator = None
        self._repository = repository

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
        # 与业务 DocxService 共享仓储时注册生成记录，下载端点才能找到产物
        if self._repository is not None:
            self._repository.save_output(
                {
                    "file_id": outcome.filename,
                    "session_id": meta.get("session_id", ""),
                    "file_path": outcome.file_path,
                    "filename": outcome.filename,
                    "word_count": outcome.word_count,
                    "template_id": template_id,
                }
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
        "ring1", "ring2", "ring3", "ring4", "ring5", "ring6", "ring7", "ring8", "ring9",
        "ring10", "docx",
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
        self.ring2: Optional[Dict[str, Any]] = None
        self.ring3: Optional[Dict[str, Any]] = None
        self.ring4: Optional[Dict[str, Any]] = None
        self.ring5: Optional[Dict[str, Any]] = None
        self.ring6: Optional[Dict[str, Any]] = None
        self.ring7: Optional[Dict[str, Any]] = None
        self.ring8: Optional[Dict[str, Any]] = None
        self.ring9: Optional[Dict[str, Any]] = None
        self.ring10: Optional[Dict[str, Any]] = None
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
        rec.ring1 = {"candidates": candidates, "chosen": chosen_title, "compliant": True}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R1", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R1", target_ring_no=2)
        return Result.ok(data={"candidates": candidates, "chosen": chosen_title,
                               "recommendation": data.get("recommendation", "")},
                         msg="环1选题完成")

    # ------------------------------------------------------------------
    # 步骤 3.5：环2 开题评审（UC-02 延续）
    # ------------------------------------------------------------------
    def run_ring2(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环2开题评审：真实检索相似研究 → 新颖度判定（LOW 回退环1）。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(2).execute(ctx)
        data = json.loads(res.output)
        rec.ring2 = data
        data["compliant"] = bool(res.accept)
        if not res.accept:
            # 评审未通过：返回错误语义（fallbackTo=1 由执行体产出）
            return Result.fail(
                code=101200,
                msg=f"环2评审未通过：{data.get('recommendation', '')}",
                data={
                    "novelty_level": data.get("novelty_level", ""),
                    "similar_count": data.get("similar_count", 0),
                    "recommendation": data.get("recommendation", ""),
                    "fallbackTo": 1,
                },
            )
        if res.accept:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R2", accept=True,
                              artifact_uri=res.output)
            self._advance_to(task_id, f"{task_id}-R2", target_ring_no=3)  # 自动过环2 → 环3
        return Result.ok(data={
            "novelty_level": data.get("novelty_level", ""),
            "similar_count": data.get("similar_count", 0),
            "differ_from_prior": data.get("differ_from_prior", ""),
            "recommendation": data.get("recommendation", ""),
            "fallbackTo": None if res.accept else 1,
        }, msg=f"环2开题评审完成：{data.get('novelty_level', '')}" if res.accept else f"环2评审未通过：{data.get('recommendation', '')}")

    # ------------------------------------------------------------------
    # 步骤 3.75：环4 综述评审（UC-03 前哨）
    # ------------------------------------------------------------------
    def run_ring4(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环4综述评审：池内竞争度 + 创新点包住检查（需重评估回退环2）。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            literature=pool,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(4).execute(ctx)
        data = json.loads(res.output)
        rec.ring4 = data
        data["compliant"] = bool(res.accept)
        if res.accept:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R4", accept=True,
                              artifact_uri=res.output)
            self._advance_to(task_id, f"{task_id}-R4", target_ring_no=5)  # 自动过环4 → 环5
        else:
            return Result.fail(
                code=101200,
                msg=f"环4评审未通过：{data.get('recommendation', '')}",
                data={
                    "verdict": data.get("verdict", ""),
                    "overlap_count": data.get("overlap_count", 0),
                    "recommendation": data.get("recommendation", ""),
                    "fallbackTo": res.fallbackTo,
                },
            )

    # ------------------------------------------------------------------
    # 步骤 3.7：环3 文献调研（显式入口）
    # ------------------------------------------------------------------
    def run_ring3(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环3文献调研：真实检索建池（显式入口，推进到环4）。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        # 产物已缓存到 rec.ring3（_ensure_literature 内执行），推进到环4
        if rec.ring3 is not None:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R3", accept=True,
                              artifact_uri=json.dumps(rec.ring3))
            self._advance_to(task_id, f"{task_id}-R3", target_ring_no=4)
        return Result.ok(data={
            "total": len(pool),
            "items": rec.ring3.get("items", []) if rec.ring3 else [],
            "summary": rec.ring3.get("summary", "") if rec.ring3 else "文献池为空",
        }, msg="环3文献调研完成" if rec.ring3 else "环3文献检索失败/禁用，池为空")

    # ------------------------------------------------------------------
    # 步骤 4：环5 大纲（UC-03）
    # ------------------------------------------------------------------
    def run_ring5(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环5大纲：基于选题生成章节结构，并推进 FSM。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            literature=pool,
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
                     "theme": outline.get("theme", chosen), "compliant": True}
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
        pool = self._ensure_literature(rec, chosen)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            outline=outline_text,
            literature=pool,
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
                     "total_words": draft.get("total_words", 0),
                     "used_refs": draft.get("used_refs", []), "compliant": True}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R6", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R6", target_ring_no=7)
        return Result.ok(data={"chapters": chapters, "total_words": draft.get("total_words", 0),
                               "content_preview": full_content[:200]}, msg="环6撰写完成")

    # ------------------------------------------------------------------
    # 步骤 6：环7 润色（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring7(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环7润色：对环6 初稿做表达润色 + 术语统一，只改表达不改事实。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        draft = (rec.ring6 or {}).get("chapters", [])
        # ring6 产物可能是 chapters 列表，序列化为 JSON 供环7 解析
        draft_json = json.dumps({"chapters": draft}, ensure_ascii=False)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            draft=draft_json,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(7).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环7润色未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        data = json.loads(res.output)
        polished = data.get("chapters", [])
        full_content = self._draft_to_text(polished)
        rec.ring7 = {"chapters": polished, "content": full_content,
                     "total_words": data.get("total_words", 0), "compliant": True}
        self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R7", accept=True,
                          artifact_uri=res.output)
        self._advance_to(task_id, f"{task_id}-R7", target_ring_no=8)
        return Result.ok(data={
            "chapters": polished,
            "total_words": data.get("total_words", 0),
            "applied_terms": data.get("applied_terms", []),
            "issues_found": data.get("issues_found", []),
        }, msg="环7润色完成（只改表达不改事实）")

    # ------------------------------------------------------------------
    # 步骤 7：环9 排版检查（UC-04 延续）
    # ------------------------------------------------------------------
    def run_ring9(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环9排版合规检查：对 docx 产物做版式检查（只查不改）。"""
        rec = self._require(task_id)
        docx = rec.docx or {}
        docx_path = ""
        # rec.docx 存的是 file_id/下载信息；实际文件路径需从生成链路拿。
        # 兜底：扫描最近生成产物（按 session/文件名）或要求先 generate_docx。
        if not docx:
            raise BizException(ErrorCode.DOCX_GENERATE_FAILED,
                              msg="请先运行 docx 生成（generate_docx），再执行排版检查",
                              detail={"task_id": task_id})
        # 从 docx 记录中找落盘路径（generate 时 RealDocxRenderer 存了 filename）
        import glob as _glob
        import os as _os
        fn = docx.get("filename", "")
        outputs_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))), "thesis_docx", "storage", "outputs")
        if fn:
            p = _os.path.join(outputs_dir, fn)
            if _os.path.exists(p):
                docx_path = p
        if not docx_path:
            cands = sorted(_glob.glob(_os.path.join(outputs_dir, "*_thesis_render.docx")),
                           key=_os.path.getmtime, reverse=True)
            docx_path = cands[0] if cands else ""

        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.docx_path = docx_path  # extra 字段（ExecContext extra=allow）
        ctx.template_path = str(rec.template_id or "")

        res = get_executor(9).execute(ctx)
        data = json.loads(res.output)
        rec.ring9 = data
        data["compliant"] = bool(res.accept)
        if res.accept:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R9", accept=True,
                              artifact_uri=res.output)
            self._advance_to(task_id, f"{task_id}-R9", target_ring_no=10)
        return Result.ok(data={
            "compliant": data.get("compliant", False),
            "issue_count": len(data.get("issues", [])),
            "summary": data.get("summary", ""),
        }, msg="环9排版检查完成" if res.accept else f"环9排版检查未通过：{data.get('summary', '')}")

    # ------------------------------------------------------------------
    # 步骤 6.5：环8 引用校验（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring8(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环8引用校验：把环6 引用的 [L序号] 映射为池内题录 → 多源核验。"""
        rec = self._require(task_id)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        pool_by_idx = {i + 1: it for i, it in enumerate(pool)}

        # 从环6 产物收集 used_refs 对应的题录
        ring6 = rec.ring6 or {}
        used_refs = (ring6.get("used_refs") or []) if isinstance(ring6, dict) else []
        refs = []
        for ref in used_refs:
            m = re.match(r"\[L(\d+)\]", ref)
            if m and int(m.group(1)) in pool_by_idx:
                it = pool_by_idx[int(m.group(1))]
                refs.append({"title": it.get("title", "") or it.get("ref_title", ""),
                             "doi": it.get("doi", "")})
        # 无 used_refs → 用池内前 5 条做示范校验（保证环8 有数据可跑）
        if not refs and pool:
            refs = [{"title": p.get("title", ""), "doi": p.get("doi", "")} for p in pool[:5]]

        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.references = refs  # extra 字段
        res = get_executor(8).execute(ctx)
        data = json.loads(res.output)
        rec.ring8 = data
        data["compliant"] = bool(res.accept)
        if res.accept:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R8", accept=True,
                              artifact_uri=res.output)
            self._advance_to(task_id, f"{task_id}-R8", target_ring_no=9)
        return Result.ok(data={
            "total": data.get("total", 0),
            "passed": data.get("passed", 0),
            "uncertain": data.get("uncertain", 0),
            "failed": data.get("failed", 0),
        }, msg=f"环8引用校验完成：{data.get('summary', '')}" if res.accept else f"环8引用校验未通过：{data.get('summary', '')}")

    # ------------------------------------------------------------------
    # 步骤 7.5：环10 定稿汇总（UC-05）
    # ------------------------------------------------------------------
    def run_ring10(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环10定稿：汇总环1~9 验收状态 + 一致性/材料检查 + 交付清单。"""
        rec = self._require(task_id)
        artifacts: Dict[str, Any] = {}
        for no in range(1, 10):
            art = getattr(rec, f"ring{no}")
            if art is not None:
                artifacts[f"ring{no}"] = art
        if rec.docx:
            artifacts["docx"] = rec.docx
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.artifacts = artifacts  # extra 字段
        res = get_executor(10).execute(ctx)
        data = json.loads(res.output)
        rec.ring10 = data
        if res.accept:
            self._fsm.advance(task_id=task_id, biz_req_no=f"{task_id}-R10", accept=True,
                              artifact_uri=res.output)
            self._advance_to(task_id, f"{task_id}-R10", target_ring_no=10)
        return Result.ok(data=data,
                         msg=f"环10定稿：{data.get('summary', '')}" if res.accept
                         else f"环10未通过：{data.get('summary', '')}")

    # ------------------------------------------------------------------
    # 步骤 8：生成 docx（UC-04）
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

    def _ensure_literature(self, rec: TaskRecord, theme: str) -> List[Dict[str, Any]]:
        """确保文献池已构建（执行环3 并缓存），返回池条目列表。

        环3 离线/无文献源时返回空池（环5/6 prompt 会提示"禁止引用"）。
        已知库文献（用户从引导层平台下载的）合并入池。
        """
        if rec.ring3 is not None:
            return rec.ring3.get("items", [])
        # 读会话知识库已存文献（用户下载的题录）
        kb_files = []
        if rec.session_id:
            try:
                from knowledge.store import get_kb_store

                kb_files = get_kb_store().list_documents(rec.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("知识库读取失败: %s", exc)
        try:
            res = get_executor(3).execute(
                ExecContext(
                    subject_field=rec.subject_field,
                    degree=Degree(rec.degree),
                    theme=theme,
                    scope="all",
                    kb_files=kb_files,
                    session_id=rec.session_id,
                    tenant_id=rec.tenant_id,
                )
            )
            data = json.loads(res.output)
            rec.ring3 = data
            return data.get("items", [])
        except Exception:  # noqa: BLE001 - 检索失败不阻塞大纲/撰写流程
            return []

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
