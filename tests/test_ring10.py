# -*- coding: utf-8 -*-
"""环10 定稿汇总测试。

验证：
    1. 全环节通过（artifacts 各环 compliant=True）→ accept=True + 材料齐备。
    2. 有环未跑 → accept=False + 列出。
    3. 材料不全（无 docx）→ missing 列出。
    4. 一致性：题目与内容无关联 → consistency 提示。
"""
from __future__ import annotations

import json

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor


def _artifacts_all_pass() -> dict:
    arts = {}
    for no in range(1, 10):
        arts[f"ring{no}"] = {"compliant": True}
    arts["docx"] = {"file_id": "FILE-X"}
    arts["ring9"] = {"compliant": True}
    arts["ring8"] = {"compliant": True, "total": 5, "passed": 5}
    # 补充环1/环6 内容（保留 compliant 键，不覆盖）
    arts["ring1"] = {**arts["ring1"], "recommendation": "基于深度学习的图像识别研究，创新点聚焦场景适配。"}
    arts["ring6"] = {**arts["ring6"], "content": "图像识别是计算机视觉核心，本研究基于深度学习展开。"}
    return arts


class TestRing10:
    def test_all_pass(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER,
                          theme="基于深度学习的图像识别研究")
        ctx.artifacts = _artifacts_all_pass()
        res = get_executor(10).execute(ctx)
        assert res.accept is True, res.issues
        data = json.loads(res.output)
        assert len(data["rings"]) == 9
        assert all(r["status"] == "通过" for r in data["rings"])
        assert data["materials_missing"] == []

    def test_ring_missing_fails(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        ctx.artifacts = {}  # 全未跑
        res = get_executor(10).execute(ctx)
        assert res.accept is False
        data = json.loads(res.output)
        assert any(r["status"] == "未跑" for r in data["rings"])
        assert "环1未通过" in str(res.issues) or any("未跑" in i for i in res.issues)

    def test_materials_incomplete(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        ctx.artifacts = {"ring1": {"compliant": True}, "ring5": {"compliant": True},
                         "ring6": {"compliant": True}}
        res = get_executor(10).execute(ctx)
        data = json.loads(res.output)
        assert res.accept is False
        assert "论文正文（docx）" in data["materials_missing"]
        assert "参考文献表" in data["materials_missing"]

    def test_consistency_mismatch_flagged(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER,
                          theme="量子计算与超导电路研究")
        ctx.artifacts = _artifacts_all_pass()  # 内容全是图像识别，无量子
        res = get_executor(10).execute(ctx)
        data = json.loads(res.output)
        # 题目"量子"未出现在摘要/正文 → consistency 应提示（但不致命）
        assert any(c["category"] == "consistency" for c in data["consistency"])
