"""单文件工作台的结构、真实 API 接线与脚本语法看门。"""

from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


UI_PATH = Path(__file__).resolve().parents[1] / "ui" / "index.html"
CYTOSCAPE_PATH = UI_PATH.parent / "vendor" / "cytoscape.min.js"


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


def test_cytoscape_is_vendored_locally():
    assert CYTOSCAPE_PATH.is_file()
    assert CYTOSCAPE_PATH.stat().st_size > 300_000


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
        'id="login-form"',
        '/api/v1/auth/login',
        '/api/v1/auth/audit',
        'id="session-search"',
        'for="session-search"',
        'id="session-search-status"',
        'aria-current="true"',
        'bindSessionSearch',
        'resolveSessionSelection',
        'filterSessions',
        'apiSelectCandidate',
        'apiCurateLiterature',
        'apiReopenStage',
        'const form = event.currentTarget',
        'Math.min(pollDelay * 1.6, 5000)',
        'data-action="generate-all-sections"',
        './vendor/cytoscape.min.js',
        'relevance_score',
        'literature-relevance',
        'id="inference-form"',
        'id="inference-api-key" type="password" autocomplete="off"',
        '/api/v1/console/provider/deepseek',
        'applyDeepSeekConfigView',
        'syncDeepSeekPresetCapabilities',
    ):
        assert fragment in html
    assert "localStorage.setItem('inference-api-key'" not in html
    assert 'OpenAI / Anthropic' not in html


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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_session_selection_and_search_helpers():
    script = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');
const start = html.indexOf('function resolveSessionSelection');
const end = html.indexOf('function formatI18n');
if (start < 0 || end <= start) throw new Error('session helpers not found');
const helpers = html.slice(start, end);
const run = new Function('DEGREE_LABEL', `${helpers}
  const items = [
    { task_id: 'one', title: 'AI 写作 🤖', subject_field: 'Natural Language', degree: 'MASTER', current_ring_no: 3 },
    { task_id: 'two', title: '教育评价', subject_field: '教育学', degree: 'PHD', current_ring_no: 5 },
  ];
  if (resolveSessionSelection(items, 'two').task_id !== 'two') throw new Error('selection was not retained');
  if (resolveSessionSelection(items, 'missing').task_id !== 'one') throw new Error('stale selection did not fall back');
  if (resolveSessionSelection([], 'missing') !== null) throw new Error('empty selection must be null');
  if (filterSessions(items, '  ai  ')[0].task_id !== 'one') throw new Error('case/space search failed');
  if (filterSessions(items, '博士')[0].task_id !== 'two') throw new Error('degree search failed');
  if (filterSessions(items, '🤖')[0].task_id !== 'one') throw new Error('emoji search failed');
  if (filterSessions(items, '完全不存在').length !== 0) throw new Error('no-match search failed');
`);
run({ BACHELOR: '本科', MASTER: '硕士', PHD: '博士' });
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(UI_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
