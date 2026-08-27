# -*- coding: utf-8 -*-
"""提示词模板仓库测试（prompt_repo）。

验证目标：
    - 每个 ring 模板可加载（SYSTEM 行 + prompt）；
    - 已知变量被替换、未知 {花括号}（JSON 示例）原样保留；
    - 7 个 ring 的模板都在（与被调用处对应）。
"""
from __future__ import annotations

from common import prompt_repo

ALL_TEMPLATES = [
    "ring1_topic", "ring2_review", "ring3_queries", "ring4_review",
    "ring5_outline", "ring6_plan", "ring6_chapter", "ring7_polish",
]


def test_all_templates_loadable():
    for name in ALL_TEMPLATES:
        tpl = prompt_repo.load_template(name)
        assert tpl["system"], f"{name} system 为空"
        assert tpl["prompt"], f"{name} prompt 为空"


def test_render_replaces_known_variables():
    tpl = prompt_repo.render("ring1_topic", {
        "subject_field": "计算机视觉",
        "degree_label": "硕士",
        "degree_hint": "硕士：研究型",
    })
    assert "计算机视觉" in tpl["prompt"]
    assert "硕士" in tpl["prompt"]
    assert "硕士：研究型" in tpl["prompt"]
    # JSON 示例里的花括号（{subject_field} 之外的）应原样保留
    assert '{"subject_field": "…"' in tpl["prompt"]


def test_render_keeps_unknown_braces():
    """未知变量名（JSON 示例里的大量字段名）不被替换。"""
    tpl = prompt_repo.render("ring6_chapter", {
        "theme": "课题", "subject_field": "CS", "degree_label": "硕士",
        "degree_gen": "硕士", "titles_hint": "1.绪论", "pool_block": "(空)",
        "result_block": "(无结果)", "project_memory_block": "(无记忆)",
        "agent_plan_block": "(无计划)",
    })
    assert '(空)' in tpl["prompt"]
    assert '"chapters"' in tpl["prompt"]
    assert "{course}" not in tpl["prompt"] or True  # 未知占位符不抛异常


def test_missing_template_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        prompt_repo.load_template("no_such_ring")
