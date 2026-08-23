"""实验执行与结果血缘的 SQLite 登记表。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import ExperimentRun, ExperimentStatus, ResultRecord


class ResearchRegistryError(ValueError):
    """违反实验状态、材料血缘或任务隔离约束。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_TRANSITIONS: dict[ExperimentStatus, set[ExperimentStatus]] = {
    ExperimentStatus.PLANNED: {
        ExperimentStatus.PLANNED,
        ExperimentStatus.MATERIALS_READY,
        ExperimentStatus.CANCELLED,
    },
    ExperimentStatus.MATERIALS_READY: {
        ExperimentStatus.MATERIALS_READY,
        ExperimentStatus.RUNNING,
        ExperimentStatus.CANCELLED,
    },
    ExperimentStatus.RUNNING: {
        ExperimentStatus.RUNNING,
        ExperimentStatus.COMPLETED,
        ExperimentStatus.FAILED,
        ExperimentStatus.CANCELLED,
    },
    ExperimentStatus.COMPLETED: set(),
    ExperimentStatus.FAILED: set(),
    ExperimentStatus.CANCELLED: set(),
}


class ResearchExecutionRegistry:
    """登记真实实验/研究执行材料及可复算结果。"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_experiment_run (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                protocol_artifact_id TEXT NOT NULL,
                status TEXT NOT NULL,
                material_file_ids TEXT NOT NULL DEFAULT '[]',
                raw_data_file_ids TEXT NOT NULL DEFAULT '[]',
                code_file_ids TEXT NOT NULL DEFAULT '[]',
                log_file_ids TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                user_attested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_experiment_run_task
            ON t_experiment_run(task_id, protocol_artifact_id, created_at);

            CREATE TABLE IF NOT EXISTS t_result_record (
                result_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                value TEXT NOT NULL,
                source_file_id TEXT NOT NULL,
                computation TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                table_or_figure_id TEXT NOT NULL DEFAULT '',
                verified_by_user INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES t_experiment_run(run_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_result_record_task
            ON t_result_record(task_id, run_id, created_at);
            """
        )
        self._db.commit()

    def create_run(self, *, task_id: str, protocol_artifact_id: str, notes: str = "") -> ExperimentRun:
        if not task_id.strip():
            raise ResearchRegistryError("task_id 不能为空")
        if not protocol_artifact_id.strip():
            raise ResearchRegistryError("protocol_artifact_id 不能为空")
        run_id = f"RUN-{uuid.uuid4().hex[:20].upper()}"
        now = _utc_now()
        with self._lock:
            self._db.execute(
                "INSERT INTO t_experiment_run(run_id, task_id, protocol_artifact_id, status, "
                "notes, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, task_id, protocol_artifact_id, ExperimentStatus.PLANNED.value,
                    notes.strip(), now, now,
                ),
            )
            self._db.commit()
        return self.get_run(task_id, run_id)

    def update_run(
        self,
        *,
        task_id: str,
        run_id: str,
        status: ExperimentStatus,
        material_file_ids: Iterable[str] | None = None,
        raw_data_file_ids: Iterable[str] | None = None,
        code_file_ids: Iterable[str] | None = None,
        log_file_ids: Iterable[str] | None = None,
        notes: str | None = None,
        user_attested: bool | None = None,
    ) -> ExperimentRun:
        current = self.get_run(task_id, run_id)
        if not isinstance(status, ExperimentStatus):
            raise ResearchRegistryError("status 非法")
        if status not in _TRANSITIONS[current.status]:
            raise ResearchRegistryError(
                f"实验状态不能从 {current.status.value} 变为 {status.value}"
            )

        def _files(new: Iterable[str] | None, old: tuple[str, ...]) -> tuple[str, ...]:
            if new is None:
                return old
            return tuple(dict.fromkeys(str(item).strip() for item in new if str(item).strip()))

        candidate = ExperimentRun(
            run_id=current.run_id,
            protocol_artifact_id=current.protocol_artifact_id,
            status=status,
            material_file_ids=_files(material_file_ids, current.material_file_ids),
            raw_data_file_ids=_files(raw_data_file_ids, current.raw_data_file_ids),
            code_file_ids=_files(code_file_ids, current.code_file_ids),
            log_file_ids=_files(log_file_ids, current.log_file_ids),
            notes=current.notes if notes is None else notes.strip(),
            user_attested=current.user_attested if user_attested is None else bool(user_attested),
        )
        if status != ExperimentStatus.COMPLETED and user_attested is True:
            raise ResearchRegistryError("实验真实性确认只能随 COMPLETED 状态提交")
        if status in {
            ExperimentStatus.MATERIALS_READY,
            ExperimentStatus.RUNNING,
            ExperimentStatus.COMPLETED,
        } and not candidate.material_file_ids:
            raise ResearchRegistryError("进入材料就绪及后续状态前必须登记实验材料")
        with self._lock:
            self._db.execute(
                "UPDATE t_experiment_run SET status=?, material_file_ids=?, raw_data_file_ids=?, "
                "code_file_ids=?, log_file_ids=?, notes=?, user_attested=?, updated_at=? "
                "WHERE task_id=? AND run_id=?",
                (
                    candidate.status.value, _json_dump(candidate.material_file_ids),
                    _json_dump(candidate.raw_data_file_ids), _json_dump(candidate.code_file_ids),
                    _json_dump(candidate.log_file_ids), candidate.notes,
                    int(candidate.user_attested), _utc_now(), task_id, run_id,
                ),
            )
            self._db.commit()
        return self.get_run(task_id, run_id)

    def get_run(self, task_id: str, run_id: str) -> ExperimentRun:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_experiment_run WHERE task_id=? AND run_id=?",
                (task_id, run_id),
            ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"当前任务中不存在实验运行: {run_id}")
        return self._row_to_run(row)

    def list_runs(self, task_id: str, protocol_artifact_id: str = "") -> list[ExperimentRun]:
        query = "SELECT * FROM t_experiment_run WHERE task_id=?"
        args: list[Any] = [task_id]
        if protocol_artifact_id:
            query += " AND protocol_artifact_id=?"
            args.append(protocol_artifact_id)
        query += " ORDER BY created_at, run_id"
        with self._lock:
            rows = self._db.execute(query, tuple(args)).fetchall()
        return [self._row_to_run(row) for row in rows]

    def add_result(
        self,
        *,
        task_id: str,
        run_id: str,
        metric: str,
        value: str,
        source_file_id: str,
        computation: str,
        unit: str = "",
        table_or_figure_id: str = "",
    ) -> ResultRecord:
        run = self.get_run(task_id, run_id)
        if run.status != ExperimentStatus.COMPLETED:
            raise ResearchRegistryError("只有已完成并由用户确认的实验才能登记结果")
        registered_files = set(
            run.material_file_ids + run.raw_data_file_ids + run.code_file_ids + run.log_file_ids
        )
        if source_file_id not in registered_files:
            raise ResearchRegistryError("结果 source_file_id 未登记在该实验运行材料中")
        result = ResultRecord(
            result_id=f"RES-{uuid.uuid4().hex[:20].upper()}",
            run_id=run_id,
            metric=metric.strip(),
            value=str(value).strip(),
            source_file_id=source_file_id.strip(),
            computation=computation.strip(),
            unit=unit.strip(),
            table_or_figure_id=table_or_figure_id.strip(),
            verified_by_user=False,
        )
        now = _utc_now()
        with self._lock:
            self._db.execute(
                "INSERT INTO t_result_record(result_id, task_id, run_id, metric, value, "
                "source_file_id, computation, unit, table_or_figure_id, verified_by_user, "
                "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    result.result_id, task_id, run_id, result.metric, result.value,
                    result.source_file_id, result.computation, result.unit,
                    result.table_or_figure_id, now, now,
                ),
            )
            self._db.commit()
        return self.get_result(task_id, result.result_id)

    def review_result(
        self, task_id: str, result_id: str, *, verified_by_user: bool
    ) -> ResultRecord:
        self.get_result(task_id, result_id)
        with self._lock:
            self._db.execute(
                "UPDATE t_result_record SET verified_by_user=?, updated_at=? "
                "WHERE task_id=? AND result_id=?",
                (int(verified_by_user), _utc_now(), task_id, result_id),
            )
            self._db.commit()
        return self.get_result(task_id, result_id)

    def get_result(self, task_id: str, result_id: str) -> ResultRecord:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_result_record WHERE task_id=? AND result_id=?",
                (task_id, result_id),
            ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"当前任务中不存在结果: {result_id}")
        return self._row_to_result(row)

    def list_results(self, task_id: str, run_id: str = "") -> list[ResultRecord]:
        query = "SELECT * FROM t_result_record WHERE task_id=?"
        args: list[Any] = [task_id]
        if run_id:
            query += " AND run_id=?"
            args.append(run_id)
        query += " ORDER BY created_at, result_id"
        with self._lock:
            rows = self._db.execute(query, tuple(args)).fetchall()
        return [self._row_to_result(row) for row in rows]

    def audit(self, task_id: str, protocol_artifact_id: str) -> dict[str, Any]:
        runs = self.list_runs(task_id, protocol_artifact_id=protocol_artifact_id)
        completed = [run for run in runs if run.status == ExperimentStatus.COMPLETED]
        results = [
            result
            for run in completed
            for result in self.list_results(task_id, run_id=run.run_id)
        ]
        verified = [result for result in results if result.verified_by_user]
        return {
            "task_id": task_id,
            "protocol_artifact_id": protocol_artifact_id,
            "run_count": len(runs),
            "completed_run_count": len(completed),
            "result_count": len(results),
            "verified_result_count": len(verified),
            "unverified_result_ids": [
                result.result_id for result in results if not result.verified_by_user
            ],
            "runs": [run.to_dict() for run in runs],
            "results": [result.to_dict() for result in results],
        }

    def delete_task(self, task_id: str) -> dict[str, int]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                result_count = self._db.execute(
                    "DELETE FROM t_result_record WHERE task_id=?", (task_id,)
                ).rowcount
                run_count = self._db.execute(
                    "DELETE FROM t_experiment_run WHERE task_id=?", (task_id,)
                ).rowcount
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return {"runs": int(run_count), "results": int(result_count)}

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> ExperimentRun:
        return ExperimentRun(
            run_id=str(row["run_id"]),
            protocol_artifact_id=str(row["protocol_artifact_id"]),
            status=ExperimentStatus(str(row["status"])),
            material_file_ids=tuple(json.loads(str(row["material_file_ids"]))),
            raw_data_file_ids=tuple(json.loads(str(row["raw_data_file_ids"]))),
            code_file_ids=tuple(json.loads(str(row["code_file_ids"]))),
            log_file_ids=tuple(json.loads(str(row["log_file_ids"]))),
            notes=str(row["notes"]),
            user_attested=bool(row["user_attested"]),
        )

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> ResultRecord:
        return ResultRecord(
            result_id=str(row["result_id"]), run_id=str(row["run_id"]),
            metric=str(row["metric"]), value=str(row["value"]),
            source_file_id=str(row["source_file_id"]), computation=str(row["computation"]),
            unit=str(row["unit"]), table_or_figure_id=str(row["table_or_figure_id"]),
            verified_by_user=bool(row["verified_by_user"]),
        )
