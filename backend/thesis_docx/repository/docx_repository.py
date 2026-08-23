# -*- coding: utf-8 -*-
"""docx 模板/生成记录仓库。

自包含实现（不依赖 db/models），提供两类后端：
    1) 内存 backend：纯内存 dict，测试闭环可用，无外部 DB 依赖；
    2) SQLAlchemy ORM backend：落地 `t_docx_template`（见 model.DocxTemplateRecord），
       在无 DB 连接时由调用方降级到内存。
本仓库提供会话归属校验（alignment：session_id 绑定式隔离）与软删除过滤。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.aicoding.exception import BizException, ErrorCode

from ..config import DocxConfig


class TemplateRecordDict(dict):
    """模板记录（dict 子类，便于 JSON 序列化与字段点取）。"""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


class DocxRepository:
    """docx 模板/生成记录仓库。

    Args:
        config: docx 模块配置。
        backend: "memory" 或是 SQLAlchemy 会话工厂（callable -> Session）。
        engine: SQLAlchemy Engine（可选，用于建表）。
    """

    def __init__(
        self,
        config: Optional[DocxConfig] = None,
        backend: str = "memory",
        session_factory: Optional[Any] = None,
    ) -> None:
        self._config = config or DocxConfig()
        self._backend = backend
        self._session_factory = session_factory
        self._lock = threading.RLock()
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._outputs: Dict[str, Dict[str, Any]] = {}

        if self._backend == "sqlalchemy":
            # 缓存记录模型，延迟导入避免无依赖启动失败
            from ..model import DocxTemplateRecord

            self._model = DocxTemplateRecord
        else:
            self._model = None

    # ------------------------------------------------------------------ #
    # 模板 CRUD
    # ------------------------------------------------------------------ #
    def save_template(self, record: Dict[str, Any]) -> TemplateRecordDict:
        """保存模板记录，返回带默认字段的记录。"""
        rec = TemplateRecordDict(record)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rec.setdefault("created_at", now)
        rec.setdefault("updated_at", now)
        rec.setdefault("deleted", False)
        if self._backend == "sqlalchemy" and self._model is not None:
            self._orm_save(rec)
        else:
            with self._lock:
                self._templates[rec["template_id"]] = dict(rec)
        return rec

    def get_template(self, template_id: str) -> Optional[TemplateRecordDict]:
        """按 template_id 读取模板（排除软删除）。"""
        if self._backend == "sqlalchemy" and self._model is not None:
            return self._orm_get(template_id)
        with self._lock:
            rec = self._templates.get(template_id)
            if rec is None or rec.get("deleted"):
                return None
            return TemplateRecordDict(dict(rec))

    def get_template_owned(self, template_id: str, session_id: str) -> TemplateRecordDict:
        """按会话归属读取模板，校验归属。

        Raises:
            BizException: 模板不存在或 session 不匹配（越权）。
        """
        rec = self.get_template(template_id)
        if rec is None:
            raise BizException(ErrorCode.TEMPLATE_NOT_FOUND, "模板不存在", detail={"template_id": template_id})
        if session_id and self._config_owned(rec) and rec.get("session_id") != session_id:
            raise BizException(ErrorCode.FORBIDDEN, "无权访问该模板（会话不匹配）", detail={"template_id": template_id})
        return rec

    def list_templates(self, session_id: str) -> List[TemplateRecordDict]:
        """按会话列出模板。"""
        if self._backend == "sqlalchemy" and self._model is not None:
            return self._orm_list(session_id)
        with self._lock:
            result: List[TemplateRecordDict] = []
            for rec in self._templates.values():
                if rec.get("deleted"):
                    continue
                if session_id and rec.get("session_id") != session_id:
                    continue
                result.append(TemplateRecordDict(dict(rec)))
            return result

    def soft_delete_template(self, template_id: str) -> None:
        """软删除模板。"""
        if self._backend == "sqlalchemy" and self._model is not None:
            self._orm_soft_delete(template_id)
            return
        with self._lock:
            rec = self._templates.get(template_id)
            if rec:
                rec["deleted"] = True

    # ------------------------------------------------------------------ #
    # 生成记录（轻量，仅记录 file_id 指向的输出文件）
    # ------------------------------------------------------------------ #
    def save_output(self, output: Dict[str, Any]) -> TemplateRecordDict:
        """保存生成记录。"""
        rec = TemplateRecordDict(output)
        rec.setdefault(
            "created_at",
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        rec.setdefault("deleted", False)
        with self._lock:
            self._outputs[rec["file_id"]] = dict(rec)
        return rec

    def get_output(self, file_id: str) -> Optional[TemplateRecordDict]:
        """按 file_id 读取生成记录。"""
        with self._lock:
            rec = self._outputs.get(file_id)
            return TemplateRecordDict(dict(rec)) if rec else None

    def get_output_owned(self, file_id: str, session_id: str) -> TemplateRecordDict:
        """按会话归属读取生成记录，校验归属。"""
        rec = self.get_output(file_id)
        if rec is None:
            raise BizException(ErrorCode.NOT_FOUND, "生成文件不存在", detail={"file_id": file_id})
        if session_id and rec.get("session_id", "") and rec.get("session_id") != session_id:
            raise BizException(ErrorCode.FORBIDDEN, "无权访问该文件（会话不匹配）", detail={"file_id": file_id})
        return rec

    # ------------------------------------------------------------------ #
    # 会话归属策略
    # ------------------------------------------------------------------ #
    @staticmethod
    def _config_owned(rec: Dict[str, Any]) -> bool:
        """是否启用会话归属校验（记录中存在 session_id 即视为绑定式）。"""
        return bool(rec.get("session_id"))

    # ------------------------------------------------------------------ #
    # ORM backend 占位实现（无 DB 时由调用方降级到 memory）
    # ------------------------------------------------------------------ #
    def _orm_save(self, rec: Dict[str, Any]) -> None:  # pragma: no cover
        from ..model import DocxTemplateRecord  # noqa: F401

        raise NotImplementedError("SQLAlchemy backend 需注入 engine，本期默认使用 memory")

    def _orm_get(self, template_id: str) -> Optional[TemplateRecordDict]:  # pragma: no cover
        raise NotImplementedError

    def _orm_list(self, session_id: str) -> List[TemplateRecordDict]:  # pragma: no cover
        raise NotImplementedError

    def _orm_soft_delete(self, template_id: str) -> None:  # pragma: no cover
        raise NotImplementedError
