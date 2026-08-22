# -*- coding: utf-8 -*-
"""内存任务存储（含 session 绑定隔离预留）。

本期仅提供进程内内存实现（M4 状态存储二期接入）。主要承担：
    1) 任务元信息与环节产出的暂存；
    2) session_id 与 task_id 的归属校验（M9 会话隔离预留数据结构）。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TaskRecord:
    """任务记录。"""

    task_id: str
    title: str
    degree: str
    subject_field: str
    session_id: str = ""
    tenant_id: str = "default"
    template_id: Optional[str] = None
    creation: Dict[str, Any] = field(default_factory=dict)
    ring1: Optional[Dict[str, Any]] = None
    ring5: Optional[Dict[str, Any]] = None
    ring6: Optional[Dict[str, Any]] = None
    docx: Optional[Dict[str, Any]] = None


class TaskStore:
    """进程内任务存储（线程安全）。"""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._session_tasks: Dict[str, List[str]] = {}
        self._lock = threading.Lock()

    def put(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._tasks[record.task_id] = record
            if record.session_id:
                self._session_tasks.setdefault(record.session_id, [])
                if record.task_id not in self._session_tasks[record.session_id]:
                    self._session_tasks[record.session_id].append(record.task_id)
            return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._tasks[record.task_id] = record
            return record

    def belongs_to_session(self, task_id: str, session_id: str) -> bool:
        """校验任务是否属于指定会话（M9 会话隔离预留）。"""
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return False
            # 会话未指定（默认会话）视为允许访问，避免阻塞默认使用路径。
            if not session_id:
                return True
            return record.session_id == session_id

    def list_by_session(self, session_id: str) -> List[str]:
        with self._lock:
            return list(self._session_tasks.get(session_id, []))
