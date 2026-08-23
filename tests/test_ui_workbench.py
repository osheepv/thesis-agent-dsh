"""单文件工作台的结构、真实 API 接线与脚本语法看门。"""

from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


UI_PATH = Path(__file__).resolve().parents[1] / "ui" / "index.html"


class _IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))


def test_ui_has_no_duplicate_static_ids():
    parser = _IdParser()
    parser.feed(UI_PATH.read_text(encoding="utf-8"))
    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    assert duplicates == []


def test_trust_workbench_is_wired_to_real_endpoints_and_accessible_states():
    html = UI_PATH.read_text(encoding="utf-8")
    for fragment in (
        'role="tablist" aria-label="项目工作台"',
        'role="status" aria-live="polite"',
        '/writing/sections/${draftId}/revise',
        '/jobs/${jobId}/cancel',
        '/jobs/${jobId}/retry',
        '/evidence-audit',
        '/research/argument-maps',
        '/research/protocols',
        '/research/runs/${runId}/transition',
        'id="protocol-form"',
        'id="argument-claim-rows"',
        'id="research-file-input"',
        '/template/mapping',
        'data-section-action="compare"',
        'computeLineDiff',
        'AbortController',
        'showAccessibleDialog',
    ):
        assert fragment in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_inline_javascript_parses():
    script = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');
const blocks = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]).filter(Boolean);
for (const block of blocks) new Function(block);
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(UI_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
