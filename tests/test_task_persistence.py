# -*- coding: utf-8 -*-
"""_TaskStore SQLite 持久化测试（重启不丢）。

验证目标（P0 修复）：
    - SQLite 模式下 put 后，新建 store（模拟进程重启）可读到任务 + 各环产物；
    - delete 后记录消失；
    - 内存模式不落盘。
"""
from __future__ import annotations

import os

from application.service.uc_main_orchestration import TaskRecord, _TaskStore


def _rec(task_id: str = "TASK-TEST001") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        title="基于 ChatGPT 的论文写作辅助研究",
        degree="MASTER",
        subject_field="计算机科学",
        session_id="sess-1",
    )


def test_sqlite_roundtrip_survives_restart(tmp_path):
    """SQLite 模式：写入 → 新 store（模拟重启）→ 任务与环产物完整。"""
    db = str(tmp_path / "task_store.db")
    store1 = _TaskStore(db_path=db)
    rec = _rec()
    rec.ring1 = {"candidates": [{"title": "甲"}], "chosen": "甲", "compliant": True}
    rec.ring6 = {"chapters": [{"chapter_title": "第一章", "content": "正文……"}],
                 "content": "正文……", "total_words": 5, "used_refs": ["[L1]"]}
    rec.docx = {"file_id": "FILE-1", "filename": "render.docx", "file_path": str(tmp_path / "render.docx")}
    store1.put(rec)

    # 模拟进程重启：全新 store 实例读同一 db 文件
    store2 = _TaskStore(db_path=db)
    got = store2.get("TASK-TEST001")
    assert got is not None
    assert got.title == "基于 ChatGPT 的论文写作辅助研究"
    assert got.degree == "MASTER"
    assert got.session_id == "sess-1"
    assert got.ring1["chosen"] == "甲"
    assert got.ring6["chapters"][0]["chapter_title"] == "第一章"
    assert got.ring6["total_words"] == 5
    assert got.ring6["used_refs"] == ["[L1]"]
    assert got.docx["file_path"] == str(tmp_path / "render.docx")

    # 列表也能恢复
    all_recs = store2.all()
    assert len(all_recs) == 1 and all_recs[0].task_id == "TASK-TEST001"

    store2.delete("TASK-TEST001")
    assert store2.get("TASK-TEST001") is None
    assert store2.all() == []


def test_sqlite_new_task_after_restart(tmp_path):
    """重启后再新建任务也能写入（新库文件自动建表）。"""
    db = str(tmp_path / "task_store.db")
    store1 = _TaskStore(db_path=db)
    store1.put(_rec("TASK-A"))
    store2 = _TaskStore(db_path=db)
    store2.put(_rec("TASK-B"))
    assert [r.task_id for r in store2.all()] == ["TASK-A", "TASK-B"]


def test_memory_mode_not_persisted(monkeypatch):
    """内存模式：写入不落盘，新 store 读不到（测试环境默认路径）。"""
    monkeypatch.setenv("THESIS_TASK_STORE_MEMORY", "true")
    store1 = _TaskStore()
    store1.put(_rec("TASK-MEM"))
    assert store1.get("TASK-MEM") is not None
    # 新实例（内存字典为空）读不到
    store2 = _TaskStore()
    assert store2.get("TASK-MEM") is None


def test_corrupt_payload_returns_none(tmp_path):
    """脏数据防御：payload 非法 JSON 时 get 返回 None 不抛异常。"""
    db = str(tmp_path / "task_store.db")
    store1 = _TaskStore(db_path=db)
    store1.put(_rec("TASK-CORRUPT"))
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("UPDATE t_task_store SET payload='not-json{{{' WHERE task_id='TASK-CORRUPT'")
    conn.commit()
    conn.close()
    store2 = _TaskStore(db_path=db)
    assert store2.get("TASK-CORRUPT") is None
