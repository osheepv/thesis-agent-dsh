# -*- coding: utf-8 -*-
"""M5 docx 模板 ORM 模型（自包含，不依赖 db/models）。

契约表 `t_docx_template`：
    template_id / session_id / template_name / file_path / parse_status /
    placeholders(JSONB) / skeleton_sections(JSONB) / file_hash / deleted

说明：为可移植性，JSON 字段使用 SQLAlchemy `JSON` 类型（PG 下自动映射为 JSONB，
sqlite 下映射为 TEXT）。如需强制 PG JSONB，可替换为 `sqlalchemy.dialects.postgresql.JSONB`。
此处沿用 `common` 约定以 `BigInteger` 主键 + 分布式 ID 生成（std uuid 语义简化为
字符串主键，见 `id`）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, DateTime


class DocxBase(DeclarativeBase):
    """docx 模块 ORM 声明基类（与 db.Base 隔离，避免跨模块耦合）。"""


class DocxTemplateRecord(DocxBase):
    """用户上传模板表 t_docx_template（M5）。

    Attributes:
        id: 自增主键。
        template_id: 模板业务 ID（uuid 字符串，对外契约主键）。
        session_id: 会话 ID（会话绑定式隔离）。
        task_id: 关联任务 ID（可选，M2 编排预留）。
        template_name: 用户原始文件名。
        file_path: 落盘路径（随机重命名）。
        file_hash: 文件 SHA-256。
        file_size: 文件字节数。
        parse_status: PENDING / PARSED / FAILED。
        placeholders: Jinja2 占位符 JSON。
        skeleton_sections: 骨架章节 JSON。
        tenant_id: 租户 ID。
        deleted: 软删除标记。
        created_at / updated_at: 时间戳。
    """

    __tablename__ = "t_docx_template"
    __table_args__ = (
        Index("idx_docx_template_template_id", "template_id"),
        Index("idx_docx_template_session", "session_id"),
        Index("idx_docx_template_hash", "file_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    task_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    template_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    placeholders: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    skeleton_sections: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
