# -*- coding: utf-8 -*-
"""M9 会话绑定知识库（一期：下载文献落地存储 + 用户笔记）。

功能（对齐"指引链接 → 用户自行下载 → 存入会话知识库文件夹"）：
    - 无 API 中文平台走引导层，用户下载文献存入 storage/kb/{session_id}/files/。
    - 文献索引 meta.json 维护；笔记 notes/ 落盘（双链 M9 完整版预留）。
"""
from __future__ import annotations

from .store import KnowledgeStore, get_kb_store

__all__ = ["KnowledgeStore", "get_kb_store"]
