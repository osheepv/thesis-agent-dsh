# -*- coding: utf-8 -*-
"""写作者工作台聚合路由（WriterConsole）。

把主编排闭环（创建任务 / 模板解析 / 环1选题 / 环5大纲 / 环6撰写 / 生成 docx /
进度）以一组聚合 REST 端点暴露，走 `application.main` 挂载的
`MainOrchestration` 单例。

路径统一挂在 `/api/v1/console` 下，与 M1 的 `/api/v1/tasks`（原生 FSM）错开，
方便写作者按「闭环语义」调用。

所有端点返回 `Result[T]` 信封；`BizException` 由 FastAPI handler 统一转换为
`Result.fail`（见 application.main / app.py 的 exception_handler）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File

from common.aicoding.dto.result import Result
from common.aicoding.enums.degree import Degree

from ..service.uc_main_orchestration import MainOrchestration

router = APIRouter(prefix="/api/v1/console", tags=["WriterConsole"])


def get_orchestration(request: Request) -> MainOrchestration:
    """FastAPI 依赖：获取应用级主编排用例实例（取自 app.state）。"""
    return request.app.state.orchestration


def _workspace_identity(request: Request) -> tuple[str, str, str]:
    """返回 (工作区键, 租户ID, 作者ID)。

    认证关闭时使用固定 local author 身份；开启时草稿按真实用户隔离。
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return "local:default", "default", "default"
    return f"{principal.tenant_id}:{principal.user_id}", principal.tenant_id, principal.user_id


def _author_identity(request: Request) -> tuple[str, str]:
    """返回 (租户ID, 作者ID)，用于作者私有草稿的隔离与鉴权。"""
    _workspace_key, tenant_id, author_id = _workspace_identity(request)
    return tenant_id, author_id


@router.get("/provider/deepseek", response_model=None)
async def get_deepseek_provider() -> Result[Any]:
    """返回不含密钥的当前DeepSeek运行时配置。"""
    from common.llm import deepseek_model_presets, get_llm_settings

    return Result.ok(data={
        "config": get_llm_settings().public_view(),
        "models": deepseek_model_presets(),
    }, msg="DeepSeek配置")


@router.post("/provider/deepseek", response_model=None)
async def set_deepseek_provider(req: Dict[str, Any]) -> Result[Any]:
    """进程内更新DeepSeek配置；API Key不回显、不落库。"""
    from common.llm import configure_deepseek_provider, deepseek_model_presets

    try:
        config = configure_deepseek_provider(req)
        return Result.ok(data={
            "config": config,
            "models": deepseek_model_presets(),
        }, msg="DeepSeek运行时配置已更新；重启后恢复.env配置")
    except ValueError as exc:
        return Result.fail(code=2, msg=str(exc))


@router.get("/workspace", response_model=None)
async def get_workspace_state(
    request: Request,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    try:
        workspace_key, tenant_id, author_id = _workspace_identity(request)
        return orchestration.get_workspace_state(
            workspace_key, tenant_id=tenant_id, author_id=author_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/workspace", response_model=None)
async def save_workspace_state(
    request: Request,
    req: Dict[str, Any],
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    try:
        workspace_key, tenant_id, _author_id = _workspace_identity(request)
        return orchestration.save_workspace_state(
            workspace_key, req, tenant_id=tenant_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 作者私有自动草稿（未提交工作副本；不推进FSM、不创建正式版本）
# ---------------------------------------------------------------------
@router.get("/tasks/{task_id}/autosave-drafts", response_model=None)
async def list_autosave_drafts(
    request: Request,
    task_id: str,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    """列出当前作者的活动草稿元数据；列表不返回正文内容。"""
    try:
        tenant_id, author_id = _author_identity(request)
        return orchestration.list_autosave_drafts(
            task_id, tenant_id=tenant_id, author_id=author_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/autosave-drafts/{draft_key:path}", response_model=None)
async def get_autosave_draft(
    request: Request,
    task_id: str,
    draft_key: str,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    """只有草稿所有者明确请求单个草稿时返回 content_json。"""
    try:
        tenant_id, author_id = _author_identity(request)
        return orchestration.get_autosave_draft(
            task_id, draft_key, tenant_id=tenant_id, author_id=author_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.put("/tasks/{task_id}/autosave-drafts/{draft_key:path}", response_model=None)
async def save_autosave_draft(
    request: Request,
    task_id: str,
    draft_key: str,
    req: Dict[str, Any],
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    """按单调 revision 保存草稿；旧请求被拒绝，同版本不同内容返回明确冲突。"""
    try:
        tenant_id, author_id = _author_identity(request)
        return orchestration.save_autosave_draft(
            task_id, draft_key, req, tenant_id=tenant_id, author_id=author_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/autosave-drafts/{draft_key:path}/discard", response_model=None)
async def discard_autosave_draft(
    request: Request,
    task_id: str,
    draft_key: str,
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    try:
        tenant_id, author_id = _author_identity(request)
        return orchestration.discard_autosave_draft(
            task_id, draft_key, tenant_id=tenant_id, author_id=author_id
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 创建论文任务（闭环入口）
# ---------------------------------------------------------------------
@router.post("/tasks", response_model=None)
async def create_task(request: Request, req: Dict[str, Any],
                      orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    title = req.get("title", "")
    degree = req.get("degree", "MASTER")
    subject_field = req.get("subject_field", "")
    template_id = req.get("template_id")
    session_id = req.get("session_id", "")
    principal = getattr(request.state, "principal", None)
    tenant_id = principal.tenant_id if principal is not None else req.get("tenant_id", "default")
    owner_user_id = principal.user_id if principal is not None else ""
    scope = req.get("scope", "all")
    try:
        degree = Degree(degree)
    except ValueError:
        return Result.fail(code=2, msg=f"非法学位等级: {degree}", data={"degree": degree})
    return orchestration.create_task(
        title=title, degree=degree, subject_field=subject_field,
        template_id=template_id, session_id=session_id, tenant_id=tenant_id,
        scope=scope, owner_user_id=owner_user_id,
    )


@router.delete("/tasks/{task_id}", response_model=None)
async def delete_task(task_id: str, session_id: str = "",
                      orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    """删除会话（连带知识库）。"""
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.delete_task(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks", response_model=None)
async def list_tasks(request: Request, session_id: str = "",
                     orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    """会话列表（含当前进度）；可按 session 过滤。"""
    try:
        principal = getattr(request.state, "principal", None)
        return orchestration.list_tasks(
            session_id=session_id,
            tenant_id=principal.tenant_id if principal is not None else "",
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 上传 / 解析模板（可选步骤）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/template", response_model=None)
async def upload_template(task_id: str, file: Optional[UploadFile] = File(default=None),
                          session_id: str = "",
                          orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    if file is None:
        return Result.ok(data=None, msg="未上传模板，跳过解析")
    content = await file.read()
    return orchestration.upload_template(task_id, content, file.filename or "template.docx",
                                         session_id=session_id)


@router.get("/tasks/{task_id}/template", response_model=None)
async def get_template_config(task_id: str, session_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.get_template_config(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/resume", response_model=None)
async def get_resume_summary(
    request: Request,
    task_id: str,
    session_id: str = "",
    orchestration: MainOrchestration = Depends(get_orchestration),
) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        _tenant_id, author_id = _author_identity(request)
        return orchestration.get_resume_summary(task_id, author_id=author_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/template/mapping", response_model=None)
async def set_template_mapping(task_id: str, req: Dict[str, Any], session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.set_template_mapping(task_id, dict(req.get("mapping", {}) or {}))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环1 选题
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/1/execute", response_model=None)
async def ring1_execute(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring1(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环2 开题评审（新颖度）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/2/review", response_model=None)
async def ring2_review(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring2(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环4 综述评审（创新点包住）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/4/review", response_model=None)
async def ring4_review(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring4(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环5 大纲
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/5/outline", response_model=None)
async def ring5_outline(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring5(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环6 撰写
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/6/chapter", response_model=None)
async def ring6_chapter(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring6(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环3 文献调研
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/3/execute", response_model=None)
async def ring3_execute(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring3(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环7 润色
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/7/polish", response_model=None)
async def ring7_polish(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring7(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环8 引用校验
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/8/validate", response_model=None)
async def ring8_validate(task_id: str, session_id: str = "",
                         orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring8(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环9 排版检查
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/9/layout", response_model=None)
async def ring9_layout(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring9(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 环10 定稿汇总
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/10/final", response_model=None)
async def ring10_final(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.run_ring10(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/artifacts", response_model=None)
async def list_artifacts(task_id: str, session_id: str = "",
                         orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    """查看全部产物版本、依赖、审批和失效状态。"""
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_artifacts(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/memory", response_model=None)
async def create_project_memory(task_id: str, req: Dict[str, Any], session_id: str = "",
                                orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.create_project_memory(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/memory", response_model=None)
async def list_project_memories(task_id: str, session_id: str = "",
                                orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_project_memories(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/memory/{artifact_id}/review", response_model=None)
async def review_project_memory(request: Request, task_id: str, artifact_id: str,
                                req: Dict[str, Any],
                                session_id: str = "",
                                orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        principal = getattr(request.state, "principal", None)
        return orchestration.review_project_memory(
            task_id,
            artifact_id,
            approved=bool(req.get("approved", True)),
            actor=principal.username if principal is not None else "author",
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/rings/3/curate", response_model=None)
async def ring3_curate(task_id: str, req: Dict[str, Any], session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.curate_literature(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/rings/1/select", response_model=None)
async def ring1_select_candidate(task_id: str, req: Dict[str, Any], session_id: str = "",
                                 orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.select_ring1_candidate(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 证据账本（来源 → 摘录 → 论断 → 链接 → 审计）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/sources", response_model=None)
async def register_source(task_id: str, req: Dict[str, Any], session_id: str = "",
                          orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.register_source(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/sources", response_model=None)
async def list_sources(task_id: str, session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_sources(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/evidence", response_model=None)
async def add_evidence(task_id: str, req: Dict[str, Any], session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.add_evidence(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/evidence", response_model=None)
async def list_evidence(task_id: str, session_id: str = "", source_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_evidence(task_id, source_id=source_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/evidence/{evidence_id}/review", response_model=None)
async def review_evidence(task_id: str, evidence_id: str, req: Dict[str, Any],
                          session_id: str = "",
                          orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_evidence(
            task_id,
            evidence_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/claims", response_model=None)
async def add_claim(task_id: str, req: Dict[str, Any], session_id: str = "",
                    orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.add_claim(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/claims", response_model=None)
async def list_claims(task_id: str, session_id: str = "", artifact_id: str = "",
                      orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_claims(task_id, artifact_id=artifact_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/claims/{claim_id}/links", response_model=None)
async def link_claim_evidence(task_id: str, claim_id: str, req: Dict[str, Any],
                              session_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.link_claim_evidence(task_id, claim_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/evidence-audit", response_model=None)
async def audit_evidence(task_id: str, session_id: str = "", artifact_id: str = "",
                         orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.audit_evidence(task_id, artifact_id=artifact_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 分节写作、逐节审批与环6汇编
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/writing/sections/generate", response_model=None)
async def generate_section_draft(task_id: str, req: Dict[str, Any], session_id: str = "",
                                 orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.generate_section_draft(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/writing/sections", response_model=None)
async def list_section_drafts(task_id: str, session_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_section_drafts(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/writing/sections-audit", response_model=None)
async def audit_section_drafts(task_id: str, session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.audit_section_drafts(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/writing/sections/{section_draft_id}/review", response_model=None)
async def review_section_draft(task_id: str, section_draft_id: str, req: Dict[str, Any],
                               session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_section_draft(
            task_id,
            section_draft_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/writing/sections/review-all", response_model=None)
async def review_all_section_drafts(task_id: str, req: Dict[str, Any], session_id: str = "",
                                    orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_all_section_drafts(
            task_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/writing/sections/{section_draft_id}/revise", response_model=None)
async def revise_section_draft(task_id: str, section_draft_id: str, req: Dict[str, Any],
                               session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.revise_section_draft(task_id, section_draft_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/rings/6/assemble", response_model=None)
async def assemble_section_drafts(task_id: str, session_id: str = "",
                                  orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.assemble_section_drafts(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 研究协议、实验运行与结果血缘
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/research/argument-maps", response_model=None)
async def create_argument_map(task_id: str, req: Dict[str, Any], session_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.create_argument_map(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/research/argument-maps", response_model=None)
async def list_argument_maps(task_id: str, session_id: str = "",
                             orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_argument_maps(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/argument-maps/{artifact_id}/review", response_model=None)
async def review_argument_map(task_id: str, artifact_id: str, req: Dict[str, Any],
                              session_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_argument_map(
            task_id,
            artifact_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/protocols", response_model=None)
async def create_research_protocol(task_id: str, req: Dict[str, Any], session_id: str = "",
                                   orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.create_research_protocol(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/research/protocols", response_model=None)
async def list_research_protocols(task_id: str, session_id: str = "",
                                  orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_research_protocols(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/protocols/{artifact_id}/review", response_model=None)
async def review_research_protocol(task_id: str, artifact_id: str, req: Dict[str, Any],
                                   session_id: str = "",
                                   orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_research_protocol(
            task_id,
            artifact_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/runs", response_model=None)
async def create_experiment_run(task_id: str, req: Dict[str, Any], session_id: str = "",
                                orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.create_experiment_run(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/research/runs", response_model=None)
async def list_experiment_runs(task_id: str, session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_experiment_runs(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/runs/{run_id}/transition", response_model=None)
async def update_experiment_run(task_id: str, run_id: str, req: Dict[str, Any],
                                session_id: str = "",
                                orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.update_experiment_run(task_id, run_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/runs/{run_id}/results", response_model=None)
async def add_result_record(task_id: str, run_id: str, req: Dict[str, Any],
                            session_id: str = "",
                            orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.add_result_record(task_id, run_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/research/results", response_model=None)
async def list_result_records(task_id: str, session_id: str = "", run_id: str = "",
                              orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_result_records(task_id, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/results/{result_id}/review", response_model=None)
async def review_result_record(task_id: str, result_id: str, req: Dict[str, Any],
                               session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_result_record(
            task_id, result_id, verified_by_user=bool(req.get("verified_by_user", True))
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/research/audit", response_model=None)
async def audit_research(task_id: str, session_id: str = "",
                         orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.audit_research(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/result-ledgers", response_model=None)
async def create_result_ledger(task_id: str, session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.create_result_ledger(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/research/result-ledgers/{artifact_id}/review", response_model=None)
async def review_result_ledger(task_id: str, artifact_id: str, req: Dict[str, Any],
                               session_id: str = "",
                               orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.review_result_ledger(
            task_id,
            artifact_id,
            approved=bool(req.get("approved", True)),
            actor=str(req.get("actor", "author")),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 持久化后台作业（长耗时环执行/分节生成/DOCX）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/jobs", response_model=None)
async def enqueue_job(task_id: str, req: Dict[str, Any], session_id: str = "",
                      orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.enqueue_job(task_id, req)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/jobs", response_model=None)
async def list_jobs(task_id: str, session_id: str = "", limit: int = 100,
                    orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.list_jobs(task_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.get("/tasks/{task_id}/jobs/{job_id}", response_model=None)
async def get_job(task_id: str, job_id: str, session_id: str = "",
                  orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.get_job(task_id, job_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/jobs/{job_id}/cancel", response_model=None)
async def cancel_job(task_id: str, job_id: str, session_id: str = "",
                     orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.cancel_job(task_id, job_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/jobs/{job_id}/retry", response_model=None)
async def retry_job(task_id: str, job_id: str, session_id: str = "",
                    orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.retry_job(task_id, job_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 当前环产物确认（执行和推进分离）
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/rings/{ring_no}/confirm", response_model=None)
async def confirm_ring(task_id: str, ring_no: int, req: Dict[str, Any],
                       session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.confirm_ring(
            task_id=task_id,
            ring_no=ring_no,
            confirmed=bool(req.get("confirmed", True)),
            reject_reason=str(req.get("reject_reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/tasks/{task_id}/reopen", response_model=None)
async def reopen_stage(task_id: str, req: Dict[str, Any], session_id: str = "",
                       orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.reopen_stage(
            task_id,
            int(req.get("target_ring_no", 0)),
            reason=str(req.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 生成 docx
# ---------------------------------------------------------------------
@router.post("/tasks/{task_id}/docx/generate", response_model=None)
async def generate_docx(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.generate_docx(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ---------------------------------------------------------------------
# 进度
# ---------------------------------------------------------------------
@router.get("/tasks/{task_id}/progress", response_model=None)
async def task_progress(task_id: str, session_id: str = "",
                        orchestration: MainOrchestration = Depends(get_orchestration)) -> Result[Any]:
    try:
        orchestration.assert_session(task_id, session_id)
        return orchestration.progress(task_id)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def _err(exc: Exception) -> Result[Any]:
    """把 BizException / 通用异常转 Result.fail（供同步编排缺陷快速返回）。"""
    from common.aicoding.exception.biz_exception import BizException

    if isinstance(exc, BizException):
        code = int(exc.code) if exc.code.isdigit() else 0
        return Result.fail(code=code, msg=exc.msg, data={"detail": exc.detail})
    return Result.fail(code=1, msg=str(exc))
