# -*- coding: utf-8 -*-
"""M9 知识库路由（会话知识库文件管理）。

挂载：/api/v1/kb/{session_id}/files（上传/列表/下载/删除）+ /path（会话路径）。

功�功能对齐"指引链接 → 用户自行下载 → 存入会话知识库文件夹"：
    - 用户从引导层（知网/万方/NCPSSD 等）下载文献，POST 到这里存入
      storage/kb/{session_id}/files/。
    - 环5/6 可从知识库引用（文献池扩展）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from common.aicoding.dto import Result
from knowledge.store import get_kb_store

logger = logging.getLogger("thesis.kb")

router = APIRouter(prefix="/api/v1/kb", tags=["M9 knowledge"])


def _store(request: Request):
    return get_kb_store()


@router.post("/{session_id}/files", response_model=None)
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    authors: str = Form(default=""),
    year: str = Form(default=""),
    store=Depends(_store),
) -> Result:
    """上传文献到会话知识库（用户自行下载后存入）。"""
    try:
        content = await file.read()
        if not content:
            return Result.fail(code=2, msg="文件为空")
        meta = {}
        if title:
            meta["title"] = title
        if authors:
            meta["authors"] = authors.split(",")
        if year:
            meta["year"] = int(year) if year.isdigit() else year
        rec = store.save_document(session_id, file.filename or "document.pdf", content, metadata=meta)
        return Result.ok(data={
            "file_id": rec["file_id"],
            "file_name": rec["file_name"],
            "file_size": rec["file_size"],
            "kb_path": store.session_path(session_id),
        }, msg="文献已存入会话知识库")
    except Exception as exc:  # noqa: BLE001
        return Result.fail(code=1, msg=f"上传失败: {exc}")


@router.get("/{session_id}/files", response_model=None)
async def list_files(session_id: str, store=Depends(_store)) -> Result:
    """列出会话知识库文献。"""
    docs = store.list_documents(session_id)
    return Result.ok(data={"items": docs, "count": len(docs), "kb_path": store.session_path(session_id)})


@router.get("/{session_id}/files/{file_id}", response_model=None)
async def download_file(session_id: str, file_id: str, store=Depends(_store)) -> Result:
    """下载会话知识库文献。"""
    rec = store.get_document(session_id, file_id)
    if rec is None:
        return Result.fail(code=100001, msg="文件不存在")
    import os

    if not os.path.exists(rec["file_path"]):
        return Result.fail(code=100001, msg="文件已丢失")
    return FileResponse(rec["file_path"], filename=rec["file_name"])


@router.delete("/{session_id}/files/{file_id}", response_model=None)
async def delete_file(session_id: str, file_id: str, store=Depends(_store)) -> Result:
    """删除会话知识库文献。"""
    ok = store.delete_document(session_id, file_id)
    if not ok:
        return Result.fail(code=100001, msg="文件不存在")
    return Result.ok(msg="已删除")


@router.get("/{session_id}/path", response_model=None)
async def session_path(session_id: str, store=Depends(_store)) -> Result:
    """会话知识库文件夹路径（给用户展示"下载到这里"）。"""
    return Result.ok(data={"kb_path": store.session_path(session_id)})
