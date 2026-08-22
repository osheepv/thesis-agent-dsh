# -*- coding: utf-8 -*-
"""SQLAlchemy 2.0 ORM 模型（与 db/ddl.sql 对齐）。

采用 SQLAlchemy 2.0 `Mapped` 声明式风格，严格对齐 PostgreSQL 原生 DDL。
注意：本模块依赖 SQLAlchemy；如无 PostgreSQL 实例，请使用 sqlite 内存库运行测试
（TestConfig 见 backend/config）。此处模型不强制连接 PG。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    """ORM 声明基类。"""


class Task(Base):
    """论文任务表 t_task。"""

    __tablename__ = "t_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    degree: Mapped[str] = mapped_column(String(16), nullable=False)
    discipline: Mapped[Optional[str]] = mapped_column(String(128))
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_STARTED")
    current_ring: Mapped[str] = mapped_column(String(16), nullable=False, default="RING_1")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    fsm_states: Mapped[list["FsmState"]] = relationship(back_populates="task")

    __table_args__ = (
        Index("idx_task_task_no", "task_no"),
        Index("idx_task_session_id", "session_id"),
        Index("idx_task_status", "status"),
    )


class FsmState(Base):
    """FSM 状态表 t_fsm_state（M1/M4）。"""

    __tablename__ = "t_fsm_state"
    __table_args__ = (
        UniqueConstraint("task_id", "ring_type", name="uq_fsm_state_task_ring"),
        Index("idx_fsm_state_task", "task_id"),
        Index("idx_fsm_state_ring_type", "ring_type"),
        Index("idx_fsm_state_phase_state", "phase_state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("t_task.id", ondelete="CASCADE"))
    ring_type: Mapped[str] = mapped_column(String(16), nullable=False)
    phase_state: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_STARTED")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    is_hitl_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hitl_approved: Mapped[Optional[bool]] = mapped_column(Boolean)
    hitl_approver: Mapped[Optional[str]] = mapped_column(String(64))
    entry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    task: Mapped["Task"] = relationship(back_populates="fsm_states")


class Outline(Base):
    """论文大纲表 t_outline（M1 环5 产物）。"""

    __tablename__ = "t_outline"
    __table_args__ = (Index("idx_outline_task", "task_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("t_task.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    degree: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    word_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class ChapterDraft(Base):
    """章节草稿表 t_chapter_draft（M1 环6 产物）。"""

    __tablename__ = "t_chapter_draft"
    __table_args__ = (
        UniqueConstraint("task_id", "chapter_seq", name="uq_chapter_draft_task_chapter"),
        Index("idx_chapter_draft_task", "task_id"),
        Index("idx_chapter_draft_chapter", "chapter_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("t_task.id", ondelete="CASCADE"))
    chapter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_balloon: Mapped[Optional[str]] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class DocxTemplate(Base):
    """用户上传模板表 t_docx_template（M5）。"""

    __tablename__ = "t_docx_template"
    __table_args__ = (
        Index("idx_docx_template_task", "task_id"),
        Index("idx_docx_template_hash", "file_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("t_task.id", ondelete="SET NULL")
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="THESIS")
    parse_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    placeholders: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


# ============================================================
# M9 会话知识库隔离预留（二期实现）
# ============================================================


class KbCollection(Base):
    """知识库集合表 t_kb_collection（session_id 强绑定）。"""

    __tablename__ = "t_kb_collection"
    __table_args__ = (
        UniqueConstraint("session_id", "name", name="uq_kb_collection_session_name"),
        Index("idx_kb_collection_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    namespace: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512))
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class KbDocument(Base):
    """知识库文档表 t_kb_document。"""

    __tablename__ = "t_kb_document"
    __table_args__ = (
        Index("idx_kb_document_collection", "collection_id"),
        Index("idx_kb_document_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("t_kb_collection.id", ondelete="CASCADE")
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_name: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_path: Mapped[str] = mapped_column(String(512), nullable=False)
    doc_hash: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UPLOADED")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class KbChunk(Base):
    """知识库切片表 t_kb_chunk。"""

    __tablename__ = "t_kb_chunk"
    __table_args__ = (
        Index("idx_kb_chunk_document", "document_id"),
        Index("idx_kb_chunk_collection", "collection_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("t_kb_document.id", ondelete="CASCADE")
    )
    collection_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 说明：VECTOR 类型依赖 pgvector 扩展，二期安装后启用。为可移植性此处留注释。
    # embedding: Mapped[Optional[Any]] = mapped_column(NullType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


ALL_MODELS = [Task, FsmState, Outline, ChapterDraft, DocxTemplate]
KB_MODELS = [KbCollection, KbDocument, KbChunk]
