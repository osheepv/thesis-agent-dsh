"""模块化工作台的结构、真实 API 接线与脚本语法看门。"""

from __future__ import annotations

import shutil
import subprocess
import threading
import urllib.request
import re
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


UI_PATH = Path(__file__).resolve().parents[1] / "ui" / "index.html"
CYTOSCAPE_PATH = UI_PATH.parent / "vendor" / "cytoscape.min.js"
STYLE_PATH = UI_PATH.parent / "styles" / "app.css"
APP_JS_PATH = UI_PATH.parent / "js" / "app.js"
MEMORY_JS_PATH = UI_PATH.parent / "js" / "components" / "project-memory.js"
EVIDENCE_JS_PATH = UI_PATH.parent / "js" / "components" / "evidence.js"
JS_PATHS = (MEMORY_JS_PATH, EVIDENCE_JS_PATH, APP_JS_PATH)


def _ui_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (UI_PATH, STYLE_PATH, *JS_PATHS)
    )


def _js_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in JS_PATHS
    )


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


def test_ui_assets_are_split_and_referenced_locally():
    html = UI_PATH.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="./styles/app.css">' in html
    script_sources = [
        './vendor/cytoscape.min.js',
        './js/components/project-memory.js',
        './js/components/evidence.js',
        './js/app.js',
    ]
    positions = [html.index(f'<script src="{source}"></script>') for source in script_sources]
    assert positions == sorted(positions)
    assert "<style>" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    for source in ('./styles/app.css', *script_sources):
        target = (UI_PATH.parent / source.removeprefix('./')).resolve()
        assert target.is_relative_to(UI_PATH.parent.resolve())
        assert target.is_file()
    assert "function loadProjectMemoryPanel" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisProjectMemory.loadPanel" in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisProjectMemory = Object.freeze" in MEMORY_JS_PATH.read_text(encoding="utf-8")
    assert "function loadEvidencePanel" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "function apiTaskSources" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "function apiEvidenceAudit" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisEvidence.loadPanel" in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisEvidence = Object.freeze" in EVIDENCE_JS_PATH.read_text(encoding="utf-8")
    assert "function loadEvidencePanel" in EVIDENCE_JS_PATH.read_text(encoding="utf-8")


def test_split_ui_assets_are_served_with_expected_content_types():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(UI_PATH.parent), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        expected = {
            "/": {"text/html"},
            "/styles/app.css": {"text/css"},
            "/js/app.js": {"text/javascript", "application/javascript"},
            "/js/components/project-memory.js": {"text/javascript", "application/javascript"},
            "/js/components/evidence.js": {"text/javascript", "application/javascript"},
            "/vendor/cytoscape.min.js": {"text/javascript", "application/javascript"},
        }
        for path, content_types in expected.items():
            with urllib.request.urlopen(base + path, timeout=5) as response:
                assert response.status == 200
                assert response.headers.get_content_type() in content_types
                assert response.read(32)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_trust_workbench_is_wired_to_real_endpoints_and_accessible_states():
    html = UI_PATH.read_text(encoding="utf-8")
    javascript = _js_source()
    for fragment in (
        'role="tablist" aria-label="项目工作台"',
        'role="status" aria-live="polite"',
        'id="protocol-form"',
        'id="argument-claim-rows"',
        'id="research-file-input"',
        'id="login-form"',
        'id="session-search"',
        'for="session-search"',
        'id="session-search-status"',
        'id="inference-form"',
        'id="inference-api-key" type="password" autocomplete="off"',
        'id="wb-tab-memory"',
        'id="memory-form"',
        'aria-describedby="memory-help memory-error"',
        './vendor/cytoscape.min.js',
    ):
        assert fragment in html
    for fragment in (
        '/writing/sections/${draftId}/revise',
        '/jobs/${jobId}/cancel',
        '/jobs/${jobId}/retry',
        '/evidence-audit',
        '/research/argument-maps',
        '/research/protocols',
        '/research/runs/${runId}/transition',
        '/template/mapping',
        'data-section-action="compare"',
        'computeLineDiff',
        'AbortController',
        'showAccessibleDialog',
        '/api/v1/auth/login',
        '/api/v1/auth/audit',
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
        'relevance_score',
        'literature-relevance',
        '/api/v1/console/provider/deepseek',
        'applyDeepSeekConfigView',
        'syncDeepSeekPresetCapabilities',
        '/api/v1/console/tasks/${taskId}/memory',
        'loadProjectMemoryPanel',
        'window.ThesisTrustUI = Object.freeze',
        'trust-assessment',
        'done-limited',
        '结构/题录通过不代表正文证据通过',
    ):
        assert fragment in javascript
    source = _ui_source()
    assert "localStorage.setItem('inference-api-key'" not in source
    assert 'OpenAI / Anthropic' not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_external_javascript_parses():
    for path in JS_PATHS:
        completed = subprocess.run(
            [shutil.which("node") or "node", "--check", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 0, f"{path.name}: {completed.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_session_selection_and_search_helpers():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function resolveSessionSelection');
const end = source.indexOf('function formatI18n');
if (start < 0 || end <= start) throw new Error('session helpers not found');
const helpers = source.slice(start, end);
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
        [shutil.which("node") or "node", "-e", script, str(APP_JS_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
