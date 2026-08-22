# -*- coding: utf-8 -*-
"""M9 会话知识库存储服务（一期：下载文献落地 + 索引）。

设计（对齐爸爸的指引链接思路）：
    - 无 API 的中文平台（知网/万方/NCPSSD 等）走"引导层"：产品给标准检索链接，
      用户自行下载文献（PDF/题录）到**会话知识库文件夹** `storage/kb/{session_id}/`。
    - 产品零成本（不爬不充），用户用自己的账号，文献资产沉淀在会话内（M9 前置）。
    - 后续 M9 知识库完整版（双链/全文检索）在此之上扩展。

目录结构：
    storage/kb/{session_id}/
        meta.json        （会话文献索引：题录 + 文件映射）
        files/*.pdf      （用户下载的文献原文）
        notes/*.md       （用户笔记，M9 双链预留）
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("thesis.kb")

#: 知识库根目录（可环境变量覆盖）
_KB_ROOT = Path(os.getenv("THESIS_KB_ROOT", str(Path(__file__).resolve().parent.parent / "storage" / "kb")))

#: 允许的知识库文件类型
_ALLOWED_EXTS: set[str] = {".pdf", ".doc", ".docx", ".txt", ".md", ".ris", ".bib"}


def _session_dir(session_id: str) -> Path:
    """会话知识库目录（sanitize session_id 防路径穿越）。"""
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id or "default")
    return _KB_ROOT / clean


class KnowledgeStore:
    """会话知识库存储（文件落盘 + 索引 meta.json）。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or _KB_ROOT
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
    def save_document(self, session_id: str, file_name: str, content: bytes,
                      metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """保存文献文件到会话知识库，返回记录。

        Args:
            session_id: 会话 ID。
            file_name: 原文件名（保留扩展名，重命名防冲突）。
            content: 文件二进制。
            metadata: 可选题录元数据（title/authors/year 等，覆盖自动提取）。
        """
        sdir = _session_dir(session_id)
        files_dir = sdir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(file_name).suffix.lower()
        if ext not in _ALLOWED_EXTS:
            raise ValueError(f"不支持的文件类型 {ext}（仅 {', '.join(sorted(_ALLOWED_EXTS))}）")

        # 重命名落盘（uuid 防覆盖）
        safe_name = f"{uuid.uuid4().hex[:12]}_{re.sub(r'[^A-Za-z0-9._\\-]', '_', file_name)}"
        target = files_dir / safe_name
        target.write_bytes(content)

        record = {
            "file_id": uuid.uuid4().hex,
            "session_id": session_id,
            "file_name": file_name,
            "stored_name": safe_name,
            "file_path": str(target),
            "file_size": len(content),
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
            "metadata": metadata or {},
        }
        # 更新索引
        index = self._load_index(session_id)
        index["documents"].append(record)
        self._save_index(session_id, index)
        return record

    def list_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """列出会话文献（不含路径详情，含基础元数据）。"""
        index = self._load_index(session_id)
        return [
            {
                "file_id": d["file_id"],
                "file_name": d["file_name"],
                "file_size": d["file_size"],
                "uploaded_at": d["uploaded_at"],
                "metadata": d.get("metadata", {}),
            }
            for d in index.get("documents", [])
        ]

    def get_document(self, session_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        """按 file_id 取记录（含 path）。"""
        index = self._load_index(session_id)
        for d in index.get("documents", []):
            if d["file_id"] == file_id:
                return d
        return None

    def delete_document(self, session_id: str, file_id: str) -> bool:
        """删除文献文件。"""
        index = self._load_index(session_id)
        docs = index.get("documents", [])
        for i, d in enumerate(docs):
            if d["file_id"] == file_id:
                try:
                    p = Path(d["file_path"])
                    if p.exists():
                        p.unlink()
                except OSError as exc:  # noqa: BLE001
                    logger.warning("删除文件失败: %s", exc)
                docs.pop(i)
                self._save_index(session_id, index)
                return True
        return False

    def session_path(self, session_id: str) -> str:
        """会话知识库绝对路径（给用户展示用）。"""
        sdir = _session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        return str(sdir)

    # ------------------------------------------------------------------
    # 用户笔记（M9 双链前置，一期简单 md 落盘）
    # ------------------------------------------------------------------
    def save_note(self, session_id: str, title: str, content: str) -> Dict[str, Any]:
        """保存用户笔记（markdown 落盘 notes/）。"""
        sdir = _session_dir(session_id)
        notes_dir = sdir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^A-Za-z0-9_\-一-龥]", "_", title)[:40] or "note"
        fname = f"{uuid.uuid4().hex[:8]}_{safe_title}.md"
        (notes_dir / fname).write_text(content, encoding="utf-8")
        return {"file_name": fname, "path": str(notes_dir / fname)}

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------
    def _load_index(self, session_id: str) -> Dict[str, Any]:
        meta = _session_dir(session_id) / "meta.json"
        if meta.exists():
            try:
                return json.loads(meta.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                logger.warning("meta.json 损坏，重建")
        return {"session_id": session_id, "documents": [], "created_at": datetime.utcnow().isoformat() + "Z"}

    def _save_index(self, session_id: str, index: Dict[str, Any]) -> None:
        meta = _session_dir(session_id) / "meta.json"
        meta.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


#: 模块级默认实例
_store: Optional[KnowledgeStore] = None


def get_kb_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
