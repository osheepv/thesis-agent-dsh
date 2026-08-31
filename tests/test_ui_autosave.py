"""自动草稿前端运行时的确定性Node状态流测试。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUTOSAVE_JS = ROOT / "ui" / "js" / "components" / "autosave.js"
APP_JS = ROOT / "ui" / "js" / "app.js"


PREAMBLE = r"""
const assert = require('assert');
const nativeSetImmediate = setImmediate;
let currentSession = 'TASK-A';
const API_BASE = 'http://127.0.0.1:8000';
const listeners = {};

class FakeNode {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.hidden = false;
    this.value = '';
    this._text = '';
    this.handlers = {};
  }
  set textContent(value) { this._text = String(value || ''); this.children = []; }
  get textContent() { return this._text; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, fn) { this.handlers[name] = fn; }
}

global.document = { createElement: tag => new FakeNode(tag) };
global.window = global;
window.addEventListener = (name, fn) => { listeners[name] = fn; };

let nextTimer = 1;
const timers = new Map();
global.setTimeout = (fn, ms) => {
  const id = nextTimer++;
  timers.set(id, { fn, ms });
  return id;
};
global.clearTimeout = id => { timers.delete(id); };
async function drainTimers() {
  for (let round = 0; round < 10 && timers.size; round += 1) {
    const pending = [...timers.values()];
    timers.clear();
    for (const timer of pending) timer.fn();
    await new Promise(resolve => nativeSetImmediate(resolve));
  }
}

const state = {
  posts: [],
  discards: [],
  server: new Map(),
  gateFirst: false,
  firstWaiter: null,
};
function recordKey(taskId, draftKey) { return taskId + '|' + draftKey; }
function metadata(record) {
  if (!record) return null;
  return {
    draft_key: record.draft_key,
    object_type: record.object_type,
    object_id: record.object_id,
    stage_no: record.stage_no,
    base_artifact_id: record.base_artifact_id,
    base_version: record.base_version,
    revision: record.revision,
    status: record.status || 'ACTIVE',
    updated_at: 'now',
  };
}
function putServer(taskId, draftKey, payload) {
  const key = recordKey(taskId, draftKey);
  const current = state.server.get(key);
  const incoming = Number(payload.revision) || 0;
  if (current && incoming < current.revision) {
    return {
      code: 400003,
      msg: '旧快照',
      data: {
        conflict: true,
        current_revision: current.revision,
        incoming_revision: incoming,
        remote: metadata(current),
      },
    };
  }
  if (current && incoming === current.revision
      && JSON.stringify(current.content_json) !== JSON.stringify(payload.content)) {
    return {
      code: 400003,
      msg: '同版本内容不同',
      data: {
        conflict: true,
        current_revision: current.revision,
        incoming_revision: incoming,
        remote: metadata(current),
      },
    };
  }
  const record = {
    draft_key: draftKey,
    object_type: payload.object_type,
    object_id: payload.object_id,
    stage_no: payload.stage_no,
    base_artifact_id: payload.base_artifact_id,
    base_version: payload.base_version,
    revision: incoming,
    content_json: payload.content,
    status: 'ACTIVE',
  };
  state.server.set(key, record);
  return { code: 0, data: metadata(record) };
}
async function apiSaveAutosaveDraft(taskId, draftKey, payload) {
  state.posts.push({ taskId, draftKey, payload });
  if (state.gateFirst && state.posts.length === 1) {
    await new Promise(resolve => { state.firstWaiter = resolve; });
  }
  return putServer(taskId, draftKey, payload);
}
async function apiGetAutosaveDraft(taskId, draftKey) {
  const record = state.server.get(recordKey(taskId, draftKey));
  return record
    ? { code: 0, data: { ...metadata(record), content_json: record.content_json } }
    : { code: 0, data: null };
}
async function apiDiscardAutosaveDraft(taskId, draftKey, revision) {
  state.discards.push({ taskId, draftKey, revision });
  const key = recordKey(taskId, draftKey);
  const current = state.server.get(key);
  if (!current || current.revision !== revision) {
    return {
      code: 400003,
      msg: '丢弃冲突',
      data: { conflict: true, remote: metadata(current) },
    };
  }
  const discarded = {
    ...current,
    revision: current.revision + 1,
    status: 'DISCARDED',
    content_json: {},
  };
  state.server.set(key, discarded);
  return { code: 0, data: { discarded: true, draft: metadata(discarded) } };
}
global.fetch = async (url, options) => {
  const marker = '/autosave-drafts/';
  const index = String(url).indexOf(marker);
  const before = String(url).slice(0, index);
  const taskId = decodeURIComponent(before.split('/').pop());
  const draftKey = decodeURIComponent(String(url).slice(index + marker.length));
  const payload = JSON.parse(options.body);
  const result = putServer(taskId, draftKey, payload);
  return { ok: result.code === 0, json: async () => result };
};
"""


def _run_node(test_body: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js不可用")
    source = PREAMBLE + "\n" + AUTOSAVE_JS.read_text(encoding="utf-8") + "\n" + test_body
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "autosave-test.js"
        script.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [node, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr


def test_autosave_debounce_uses_latest_snapshot_and_task_binding():
    _run_node(r"""
(async () => {
  let content = { text: '' };
  const status = new FakeNode();
  const surface = window.ThesisAutosave.registerDraftSurface({
    draftKey: 'section-revision:1.1',
    taskId: 'TASK-A',
    objectType: 'SECTION_REVISION',
    objectId: '1.1',
    stageNo: 6,
    statusEl: status,
    serialize: () => ({ ...content }),
    hydrate: value => { content = { ...value }; },
  });
  content = { text: 'first' };
  window.ThesisAutosave.scheduleDraftSave(surface.draftKey);
  content = { text: 'latest' };
  window.ThesisAutosave.scheduleDraftSave(surface.draftKey);
  currentSession = 'TASK-B';
  await drainTimers();
  assert.equal(state.posts.length, 1);
  assert.equal(state.posts[0].taskId, 'TASK-A');
  assert.deepEqual(state.posts[0].payload.content, { text: 'latest' });
  assert.equal(state.posts[0].payload.revision, 1);
  assert.equal(surface.status, 'saved');
})().catch(error => { console.error(error); process.exit(1); });
""")


def test_pagehide_newer_revision_wins_and_identity_generations_do_not_block():
    _run_node(r"""
(async () => {
  state.gateFirst = true;
  let contentA = { text: 'A1' };
  const surfaceA = window.ThesisAutosave.registerDraftSurface({
    draftKey: 'project-memory:new',
    taskId: 'TASK-A',
    objectType: 'PROJECT_MEMORY_FORM',
    objectId: 'new',
    stageNo: 0,
    serialize: () => ({ ...contentA }),
    hydrate: value => { contentA = { ...value }; },
  });
  const oldSave = window.ThesisAutosave.runDraftSave(surfaceA.draftKey);
  await new Promise(resolve => nativeSetImmediate(resolve));
  assert.equal(state.posts[0].payload.revision, 1);

  contentA = { text: 'A2' };
  listeners.pagehide();
  await new Promise(resolve => nativeSetImmediate(resolve));
  assert.equal(state.server.get('TASK-A|project-memory:new').revision, 2);

  window.ThesisAutosave.resetAutosaveIdentity();
  let contentB = { text: 'B1' };
  const surfaceB = window.ThesisAutosave.registerDraftSurface({
    draftKey: 'project-memory:new',
    taskId: 'TASK-B',
    objectType: 'PROJECT_MEMORY_FORM',
    objectId: 'new',
    stageNo: 0,
    serialize: () => ({ ...contentB }),
    hydrate: value => { contentB = { ...value }; },
  });
  await window.ThesisAutosave.runDraftSave(surfaceB.draftKey);
  assert.equal(state.server.get('TASK-B|project-memory:new').revision, 1);
  state.firstWaiter();
  await oldSave;
  assert.equal(state.server.get('TASK-A|project-memory:new').revision, 2);
  assert.deepEqual(state.server.get('TASK-B|project-memory:new').content_json, { text: 'B1' });
})().catch(error => { console.error(error); process.exit(1); });
""")


def test_discard_uses_revision_tombstone_and_conflict_copy_key_is_valid():
    _run_node(r"""
(async () => {
  let content = { text: 'draft' };
  let resetCalled = 0;
  const surface = window.ThesisAutosave.registerDraftSurface({
    draftKey: 'section-revision:1.2',
    taskId: 'TASK-A',
    objectType: 'SECTION_REVISION',
    objectId: '1.2',
    stageNo: 6,
    serialize: () => ({ ...content }),
    hydrate: value => { content = { ...value }; },
    reset: () => { resetCalled += 1; content = { text: 'formal' }; },
  });
  await window.ThesisAutosave.runDraftSave(surface.draftKey);
  const response = await window.ThesisAutosave.discardDraft(surface.draftKey);
  assert.equal(response.code, 0);
  assert.equal(state.discards[0].revision, 1);
  assert.equal(surface.revision, 2);
  assert.equal(resetCalled, 1);
  assert.equal(state.server.get('TASK-A|section-revision:1.2').status, 'DISCARDED');
  const copyKey = conflictCopyKey('section-revision:1.2');
  assert.match(copyKey, /^section-revision:[A-Za-z0-9_.-]+$/);
  assert.equal(copyKey.includes('#'), false);
})().catch(error => { console.error(error); process.exit(1); });
""")


def test_section_surface_wiring_loads_and_submits_real_autosave():
    source = APP_JS.read_text(encoding="utf-8")
    assert "await window.ThesisAutosave.loadDraft(draftKey)" in source
    assert "await window.ThesisAutosave.flushDraft(autosaveKey)" in source
    assert "autosave_draft_key" in source
    assert "autosave_revision" in source
    assert "markDraftSubmitted" in source
    assert "restoreEditorAnchor" in source


def test_important_forms_use_shared_autosave_runtime_and_formal_controls():
    app = APP_JS.read_text(encoding="utf-8")
    memory = (
        ROOT / "ui" / "js" / "components" / "project-memory.js"
    ).read_text(encoding="utf-8")
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

    for key in ("research-protocol:new", "argument-map:new"):
        assert key in app
    assert "ensureResearchAutosaves" in app
    assert "buildProtocolPayload" in app
    assert "buildArgumentPayload" in app
    assert "autosave_draft_key" in app
    assert "autosave_revision" in app
    assert "PROJECT_MEMORY_DRAFT_KEY" in memory
    assert "ensureProjectMemoryAutosave" in memory
    assert "flushDraft(PROJECT_MEMORY_DRAFT_KEY)" in memory
    assert "memory-autosave-status" in html
    assert "protocol-autosave-status" in html
    assert "argument-autosave-status" in html
