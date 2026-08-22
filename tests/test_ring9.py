# -*- coding: utf-8 -*-
"""环9 格式排版测试。

用 python-docx 动态构造 docx 验证检查器：
    1. 合规 docx（含前置件顺序）→ compliant=True。
    2. 字体不对（Normal 字号异常）→ HARD，compliant=False。
    3. 前置件顺序错 → HARD。
    4. 无 docx_path → 提示先生成。
"""
from __future__ import annotations

import json
import os

import pytest
from docx import Document as _Doc

from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor
from backend.thesis_docx.compliance import DocxComplianceChecker


# ---------------------------------------------------------------------
# fixture：临时 docx
# ---------------------------------------------------------------------
@pytest.fixture()
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("ring9")


def _make_docx(path: str, font_size: float = 12.0, structure_ok: bool = True) -> str:
    """构造测试 docx。"""
    doc = _Doc()
    # 正常样式
    normal = doc.styles["Normal"]
    normal.font.size = __import__("docx").shared.Pt(font_size)
    # 前置件按顺序
    paragraphs = ["XX大学硕士学位论文", "摘要：本文研究…", "Abstract: This paper…",
                  "目录", "第1章 绪论", "参考文献", "致谢"]
    if not structure_ok:
        paragraphs = ["致谢", "第1章 绪论", "摘要：本文研究…"]
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(path)
    return path


class TestComplianceChecker:
    def test_clean_docx_compliant(self, tmp_path):
        p = _make_docx(str(tmp_path / "ok.docx"))
        report = DocxComplianceChecker().check(p)
        d = report.to_dict()
        assert d["rules_used"] == "default"
        assert d["hard_count"] == 0, f"合规文档不应有 HARD，实际: {d['issues']}"

    def test_wrong_font_hard(self, tmp_path):
        p = _make_docx(str(tmp_path / "badfont.docx"), font_size=20.0)  # 20pt vs 默认12
        d = DocxComplianceChecker().check(p).to_dict()
        assert any(i["severity"] == "HARD" for i in d["issues"]), "20pt 应判 HARD"

    def test_structure_wrong_hard(self, tmp_path):
        p = _make_docx(str(tmp_path / "badstruct.docx"), structure_ok=False)
        d = DocxComplianceChecker().check(p).to_dict()
        assert any(i["severity"] == "HARD" and i["category"] == "structure" for i in d["issues"])


class TestRing9Executor:
    def test_passes_clean(self, tmp_path):
        p = _make_docx(str(tmp_path / "ok.docx"))
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        ctx.docx_path = p
        res = get_executor(9).execute(ctx)
        data = json.loads(res.output)
        assert res.accept is True
        assert data["compliant"] is True

    def test_no_docx_fails(self):
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        res = get_executor(9).execute(ctx)
        assert res.accept is False
        assert "docx_path" not in (json.loads(res.output) or {}).get("summary", "") or "先生成" in json.loads(res.output)["summary"]

    def test_bad_font_fails(self, tmp_path):
        p = _make_docx(str(tmp_path / "bad.docx"), font_size=20.0)
        ctx = ExecContext(subject_field="CV", degree=Degree.MASTER, theme="T")
        ctx.docx_path = p
        res = get_executor(9).execute(ctx)
        assert res.accept is False
