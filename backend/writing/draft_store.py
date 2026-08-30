"""作者私有自动草稿：版本化、单调 revision、任务/租户/作者隔离。

自动草稿是**未提交的工作副本**，与正式产物严格分离：

- 保存、恢复、丢弃、冲突解决草稿都不会推进 FSM、创建正式 Artifact
  或 SectionDraft 版本、自动批准、改变当前批准版本，也不会触发模型调用。
- 只有用户明确提交（创建正式新版本）成功后，草稿才标记为 SUBMITTED。
- 每个 draft_key 拥有独立单调 revision，旧请求不能倒退覆盖新请求。

存储与 `SectionDraftRegistry` 保持同一风格（sqlite3 + RLock + 显式 SQL），
内存模式（`:memory:`）与 SQLite 模式契约一致，便于测试与进程重启验证。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

DraftObjectType = Literal[
    "SECTION_REVISION",
    "PROJECT_MEMORY_FORM",
    "RESEARCH_PROTOCOL_FORM",
    "ARGUMENT_MAP_FORM",
    "RESULT_RECORD_FORM",
]

DraftStatus = Literal["ACTIVE", "STALE", "SUBMITTED", "DISCARDED"]

DRAFT_OBJECT_TYPES: tuple[str, ...] = (
    "SECTION_REVISION",
    "PROJECT_MEMORY_FORM",
    "RESEARCH_PROTOCOL_FORM",
    "ARGUMENT_MAP_FORM",
    "RESULT_RECORD_FORM",
)

# draft_key 必须是 `<类型前缀>:<对象ID>`，禁止把标题、正文或用户路径当主键。
DRAFT_KEY_PREFIX: dict[str, str] = {
    "SECTION_REVISION": "section-revision",
    "PROJECT_MEMORY_FORM": "project-memory",
    "RESEARCH_PROTOCOL_FORM": "research-protocol",
    "ARGUMENT_MAP_FORM": "argument-map",
    "RESULT_RECORD_FORM": "result-record",
}

DRAFT_KEY_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9-]{0,31}):(?P<object>[A-Za-z0-9_.-]{1,120})$")

MAX_DRAFT_BYTES = 512 * 1024
MAX_ACTIVE_DRAFTS_PER_TASK_AUTHOR = 50
MAX_DRAFT_KEY_LENGTH = 160
MAX_STALE_REASON_LENGTH = 300


class AutosaveDraftError(ValueError):
    """草稿校验、大小、数量或状态约束被违反。"""


class AutosaveDraftRevisionConflict(ValueError):
    """草稿 revision 冲突：旧快照或同版本不同内容不得覆盖新快照。"""

    def __init__(self, remote: "AutosaveDraft", incoming_revision: int, reason: str) -> None:
        self.remote = remote
        self.current_revision = int(remote.revision)
        self.incoming_revision = int(incoming_revision)
        self.reason = reason
        super().__init__(
            f"草稿已在其他页面更新（服务端revision {self.current_revision}，"
            f"请求revision {self.incoming_revision}：{reason}），已拒绝写入"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash_of(content: Any) -> str:
    """服务端重算内容哈希，绝不信任客户端上报的 hash。"""
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def validate_draft_key(object_type: str, draft_key: str) -> str:
    """校验 draft_key 稳定、可校验、不可路径穿越，且类型前缀匹配。"""
    if object_type not in DRAFT_OBJECT_TYPES:
        raise AutosaveDraftError(f"不支持的草稿对象类型: {object_type}")
    key = str(draft_key or "").strip()
    if not key or len(key) > MAX_DRAFT_KEY_LENGTH:
        raise AutosaveDraftError("draft_key非法")
    match = DRAFT_KEY_RE.match(key)
    if not match:
        raise AutosaveDraftError(
            "draft_key必须为 `<类型前缀>:<对象ID>`，且只含字母数字、下划线、连字符和点"
        )
    expected_prefix = DRAFT_KEY_PREFIX[object_type]
    if match.group("prefix") != expected_prefix:
        raise AutosaveDraftError(
            f"draft_key前缀与对象类型不匹配，{object_type} 应使用 `{expected_prefix}:`"
        )
    return key


def draft_key_for(object_type: str, object_id: str) -> str:
    return validate_draft_key(object_type, f"{DRAFT_KEY_PREFIX[object_type]}:{object_id}")


@dataclass(frozen=True)
class AutosaveDraft:
    """一条作者私有草稿。content_json 只在详情接口对所有者返回。"""

    draft_id: str
    task_id: str
    tenant_id: str
    author_id: str
    draft_key: str
    object_type: str
    object_id: str
    stage_no: int
    base_artifact_id: str
    base_version: int
    revision: int
    content_json: dict[str, Any]
    content_hash: str
    status: str
    stale_reason: str
    submitted_to_id: str
    created_at: str
    updated_at: str

    def metadata(self) -> dict[str, Any]:
        """列表与恢复摘要使用的元数据，**绝不**包含正文内容。"""
        return {
            "draft_id": self.draft_id,
            "draft_key": self.draft_key,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "stage_no": self.stage_no,
            "base_artifact_id": self.base_artifact_id,
            "base_version": self.base_version,
            "revision": self.revision,
            "status": self.status,
            "stale_reason": self.stale_reason,
            "submitted_to_id": self.submitted_to_id,
            "updated_at": self.updated_at,
            "content_bytes": len(_canonical_json(self.content_json).encode("utf-8")),
        }

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        value = dict(self.metadata())
        if include_content:
            value["content_json"] = self.content_json
            value["content_hash"] = self.content_hash
            value["created_at"] = self.created_at
        return value


class AutosaveDraftStore:
    """按 (task_id, author_id, draft_key) 唯一的草稿仓储。

    revision 比较与写入在同一把锁内完成，因此乱序到达的请求不会互相倒退。
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS t_autosave_draft (
                    draft_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    draft_key TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    stage_no INTEGER NOT NULL DEFAULT 0,
                    base_artifact_id TEXT NOT NULL DEFAULT '',
                    base_version INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0,
                    content_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    stale_reason TEXT NOT NULL DEFAULT '',
                    submitted_to_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, author_id, draft_key)
                );

                CREATE INDEX IF NOT EXISTS idx_autosave_draft_task
                ON t_autosave_draft(task_id, author_id, status);
                """
            )
            self._db.commit()

    # ------------------------------------------------------------------
    # 写入（单调 revision 比较与写入在同一锁内）
    # ------------------------------------------------------------------
    def save(
        self,
        *,
        task_id: str,
        tenant_id: str,
        author_id: str,
        object_type: str,
        draft_key: str,
        content: Any,
        stage_no: int = 0,
        base_artifact_id: str = "",
        base_version: int = 0,
        revision: int,
    ) -> AutosaveDraft:
        if not task_id:
            raise AutosaveDraftError("task_id不能为空")
        key = validate_draft_key(object_type, draft_key)
        if not isinstance(content, dict):
            raise AutosaveDraftError("草稿内容必须是结构化JSON对象")
        try:
            incoming_revision = int(revision)
        except (TypeError, ValueError) as exc:
            raise AutosaveDraftError("revision必须是整数") from exc
        if incoming_revision < 0:
            raise AutosaveDraftError("revision不能为负数")
        try:
            stage_no = int(stage_no)
            base_version = int(base_version)
        except (TypeError, ValueError) as exc:
            raise AutosaveDraftError("stage_no与base_version必须是整数") from exc

        serialized = _canonical_json(content)
        size = len(serialized.encode("utf-8"))
        if size > MAX_DRAFT_BYTES:
            raise AutosaveDraftError(
                f"草稿超过 {MAX_DRAFT_BYTES} 字节上限（当前 {size} 字节），已拒绝保存"
            )
        content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        object_id = key.split(":", 1)[1]
        now = _utc_now()

        with self._lock:
            current = self._load_locked(task_id, author_id, key)
            if current is not None:
                if incoming_revision < current.revision:
                    raise AutosaveDraftRevisionConflict(current, incoming_revision, "旧快照")
                if incoming_revision == current.revision:
                    if current.content_hash == content_hash:
                        # 同版本同内容：幂等重放，不产生新的写入。
                        return current
                    raise AutosaveDraftRevisionConflict(
                        current, incoming_revision, "同版本内容不同"
                    )
            elif self._count_active_locked(task_id, author_id) >= MAX_ACTIVE_DRAFTS_PER_TASK_AUTHOR:
                raise AutosaveDraftError(
                    f"每任务每作者活动草稿数量上限为 {MAX_ACTIVE_DRAFTS_PER_TASK_AUTHOR}"
                )

            draft = AutosaveDraft(
                draft_id=current.draft_id if current else f"DRAFT-{uuid.uuid4().hex[:16].upper()}",
                task_id=task_id,
                tenant_id=tenant_id,
                author_id=author_id,
                draft_key=key,
                object_type=object_type,
                object_id=object_id,
                stage_no=stage_no,
                base_artifact_id=str(base_artifact_id or ""),
                base_version=base_version,
                revision=incoming_revision,
                content_json=dict(content),
                content_hash=content_hash,
                status=current.status if current and current.status == "SUBMITTED" else "ACTIVE",
                stale_reason="" if not current or current.status == "SUBMITTED"
                    else current.stale_reason,
                submitted_to_id=current.submitted_to_id if current else "",
                created_at=current.created_at if current else now,
                updated_at=now,
            )
            self._db.execute(
                "INSERT INTO t_autosave_draft("
                " draft_id, task_id, tenant_id, author_id, draft_key, object_type,"
                " object_id, stage_no, base_artifact_id, base_version, revision,"
                " content_json, content_hash, status, stale_reason, submitted_to_id,"
                " created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id, author_id, draft_key) DO UPDATE SET "
                " tenant_id=excluded.tenant_id, object_type=excluded.object_type,"
                " object_id=excluded.object_id, stage_no=excluded.stage_no,"
                " base_artifact_id=excluded.base_artifact_id,"
                " base_version=excluded.base_version, revision=excluded.revision,"
                " content_json=excluded.content_json, content_hash=excluded.content_hash,"
                " status=excluded.status, stale_reason=excluded.stale_reason,"
                " submitted_to_id=excluded.submitted_to_id, updated_at=excluded.updated_at",
                (
                    draft.draft_id, draft.task_id, draft.tenant_id, draft.author_id,
                    draft.draft_key, draft.object_type, draft.object_id, draft.stage_no,
                    draft.base_artifact_id, draft.base_version, draft.revision, serialized,
                    draft.content_hash, draft.status, draft.stale_reason,
                    draft.submitted_to_id, draft.created_at, draft.updated_at,
                ),
            )
            self._db.commit()
            return draft

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get(self, task_id: str, author_id: str, draft_key: str) -> AutosaveDraft | None:
        with self._lock:
            return self._load_locked(task_id, author_id, draft_key)

    def list_task(
        self, task_id: str, author_id: str, *, include_submitted: bool = False
    ) -> list[AutosaveDraft]:
        with self._lock:
            if include_submitted:
                rows = self._db.execute(
                    "SELECT * FROM t_autosave_draft WHERE task_id=? AND author_id=? "
                    "ORDER BY updated_at DESC",
                    (task_id, author_id),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM t_autosave_draft WHERE task_id=? AND author_id=? "
                    "AND status IN ('ACTIVE', 'STALE') ORDER BY updated_at DESC",
                    (task_id, author_id),
                ).fetchall()
            return [self._row_to_draft(row) for row in rows]

    def list_metadata(
        self, task_id: str, author_id: str, *, include_submitted: bool = False
    ) -> list[dict[str, Any]]:
        return [
            draft.metadata()
            for draft in self.list_task(task_id, author_id, include_submitted=include_submitted)
        ]

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def discard(self, task_id: str, author_id: str, draft_key: str) -> AutosaveDraft | None:
        with self._lock:
            current = self._load_locked(task_id, author_id, draft_key)
            if current is None:
                return None
            self._db.execute(
                "DELETE FROM t_autosave_draft WHERE task_id=? AND author_id=? AND draft_key=?",
                (task_id, author_id, draft_key),
            )
            self._db.commit()
            return current

    def mark_stale(
        self, task_id: str, author_id: str, draft_key: str, *, reason: str
    ) -> AutosaveDraft | None:
        """上游正式版本变化时保留内容并标记过期，禁止一键正式提交。"""
        with self._lock:
            current = self._load_locked(task_id, author_id, draft_key)
            if current is None or current.status != "ACTIVE":
                return current
            updated = self._replace_locked(
                current, status="STALE", stale_reason=str(reason or "")[:MAX_STALE_REASON_LENGTH]
            )
            self._db.commit()
            return updated

    def mark_submitted(
        self, task_id: str, author_id: str, draft_key: str, *, submitted_to_id: str
    ) -> AutosaveDraft | None:
        """正式版本创建成功之后调用；失败时必须保留 ACTIVE 草稿。"""
        with self._lock:
            current = self._load_locked(task_id, author_id, draft_key)
            if current is None:
                return None
            updated = self._replace_locked(
                current, status="SUBMITTED", submitted_to_id=str(submitted_to_id or ""),
                stale_reason="",
            )
            self._db.commit()
            return updated

    def mark_stale_by_base(
        self, task_id: str, base_artifact_id: str, current_version: int
    ) -> int:
        """把 base 版本不再是当前版本的 ACTIVE 草稿标记为 STALE。"""
        if not base_artifact_id:
            return 0
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM t_autosave_draft WHERE task_id=? AND base_artifact_id=? "
                "AND status='ACTIVE'",
                (task_id, base_artifact_id),
            ).fetchall()
            changed = 0
            for row in rows:
                draft = self._row_to_draft(row)
                if draft.base_version == current_version:
                    continue
                self._replace_locked(
                    draft,
                    status="STALE",
                    stale_reason=(
                        f"上游正式版本已由 v{draft.base_version} 更新到 v{current_version}，"
                        "请基于最新版本重新创建草稿"
                    )[:MAX_STALE_REASON_LENGTH],
                )
                changed += 1
            if changed:
                self._db.commit()
            return changed

    def delete_task(self, task_id: str) -> int:
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM t_autosave_draft WHERE task_id=?", (task_id,)
            )
            self._db.commit()
            return int(cursor.rowcount or 0)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _load_locked(self, task_id: str, author_id: str, draft_key: str) -> AutosaveDraft | None:
        row = self._db.execute(
            "SELECT * FROM t_autosave_draft WHERE task_id=? AND author_id=? AND draft_key=?",
            (task_id, author_id, draft_key),
        ).fetchone()
        return self._row_to_draft(row) if row is not None else None

    def _count_active_locked(self, task_id: str, author_id: str) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS total FROM t_autosave_draft WHERE task_id=? AND author_id=? "
            "AND status IN ('ACTIVE', 'STALE')",
            (task_id, author_id),
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def _replace_locked(self, draft: AutosaveDraft, **changes: Any) -> AutosaveDraft:
        updated = AutosaveDraft(**{**draft.__dict__, **changes, "updated_at": _utc_now()})
        self._db.execute(
            "UPDATE t_autosave_draft SET status=?, stale_reason=?, submitted_to_id=?, "
            "updated_at=? WHERE draft_id=?",
            (
                updated.status, updated.stale_reason, updated.submitted_to_id,
                updated.updated_at, updated.draft_id,
            ),
        )
        return updated

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> AutosaveDraft:
        try:
            content = json.loads(str(row["content_json"]))
        except (TypeError, ValueError):
            content = {}
        if not isinstance(content, dict):
            content = {}
        return AutosaveDraft(
            draft_id=str(row["draft_id"]),
            task_id=str(row["task_id"]),
            tenant_id=str(row["tenant_id"]),
            author_id=str(row["author_id"]),
            draft_key=str(row["draft_key"]),
            object_type=str(row["object_type"]),
            object_id=str(row["object_id"]),
            stage_no=int(row["stage_no"]),
            base_artifact_id=str(row["base_artifact_id"]),
            base_version=int(row["base_version"]),
            revision=int(row["revision"]),
            content_json=content,
            content_hash=str(row["content_hash"]),
            status=str(row["status"]),
            stale_reason=str(row["stale_reason"]),
            submitted_to_id=str(row["submitted_to_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
