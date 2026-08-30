/* Autosave runtime: author-private, unsubmitted work copies.
   Loaded before app.js; dependencies resolve at runtime.

   设计约束（H4-002）：
   - 草稿只保存/恢复用户未提交内容，绝不推进 FSM、创建正式版本或调用模型。
   - 每个 draft_key 独立单调 revision；发送时同步预留，避免 pagehide 与普通保存撞版本。
   - 身份切换为每个草稿面创建新保存世代，旧世代回包不得影响新身份。
   - 冲突后停止自动重试，由用户决定，绝不自动采用最后写入者。
*/
const AUTOSAVE_DEBOUNCE_MS = 1000;
const AUTOSAVE_STATUSES = {
  IDLE: 'idle',
  DIRTY: 'dirty',
  SAVING: 'saving',
  SAVED: 'saved',
  FAILED: 'failed',
  CONFLICT: 'conflict',
  STALE: 'stale',
  SUBMITTED: 'submitted',
};
const AUTOSAVE_STATUS_TEXT = {
  idle: '尚未修改',
  dirty: '有修改尚未保存',
  saving: '保存中…',
  saved: '已保存',
  failed: '保存失败',
  conflict: '与另一页面冲突',
  stale: '上游已变化，需要复核',
  submitted: '已正式提交',
};

const autosaveSurfaces = new Map();
let autosaveIdentityToken = 0;

function autosaveNewGeneration() {
  return {
    token: autosaveIdentityToken,
    inFlight: false,
    queued: false,
    lastSnapshot: null,
    promise: null,
  };
}

function sameDraftContent(left, right) {
  return JSON.stringify(left || null) === JSON.stringify(right || null);
}

function autosaveElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function setDraftStatus(surface, status, detail, retryable = false) {
  surface.status = status;
  surface.statusDetail = detail || '';
  const host = surface.statusEl;
  if (!host) return;
  host.textContent = '';
  host.dataset.state = status;
  const label = AUTOSAVE_STATUS_TEXT[status] || status;
  const text = detail ? `${label}：${detail}` : label;
  host.append(autosaveElement('span', 'autosave-status-text', text));
  if (retryable) {
    const retry = autosaveElement('button', 'btn btn-secondary btn-sm', '重试保存');
    retry.type = 'button';
    retry.dataset.autosaveRetry = surface.draftKey;
    retry.addEventListener('click', () => { runDraftSave(surface.draftKey, { force: true }); });
    host.append(retry);
  }
  if (status === AUTOSAVE_STATUSES.CONFLICT) showDraftConflict(surface);
  else hideDraftConflict(surface);
}

function registerDraftSurface(config) {
  if (!config || !config.draftKey || typeof config.serialize !== 'function'
      || typeof config.hydrate !== 'function') {
    throw new Error('自动草稿表面缺少draftKey、serialize或hydrate');
  }
  if (autosaveSurfaces.has(config.draftKey)) {
    unregisterDraftSurface(config.draftKey);
  }
  const surface = {
    draftKey: config.draftKey,
    taskId: config.taskId || currentSession || '',
    objectType: config.objectType,
    objectId: config.objectId || 'new',
    stageNo: config.stageNo || 0,
    label: config.label || config.draftKey,
    serialize: config.serialize,
    hydrate: config.hydrate,
    reset: typeof config.reset === 'function' ? config.reset : null,
    statusEl: config.statusEl || null,
    conflictHost: config.conflictHost || null,
    revision: 0,
    baseArtifactId: config.baseArtifactId || '',
    baseVersion: config.baseVersion || 0,
    status: AUTOSAVE_STATUSES.IDLE,
    statusDetail: '',
    timer: null,
    generation: autosaveNewGeneration(),
    remote: null,
    conflictLocal: null,
  };
  autosaveSurfaces.set(config.draftKey, surface);
  setDraftStatus(surface, AUTOSAVE_STATUSES.IDLE, '');
  return surface;
}

function unregisterDraftSurface(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface) return;
  clearTimeout(surface.timer);
  surface.taskId = '';
  surface.generation = autosaveNewGeneration();
  hideDraftConflict(surface);
  autosaveSurfaces.delete(draftKey);
}

async function loadDraft(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface || !surface.taskId) return null;
  const generation = surface.generation;
  const taskId = surface.taskId;
  const response = await apiGetAutosaveDraft(taskId, draftKey);
  if (
    autosaveSurfaces.get(draftKey) !== surface
    || generation !== surface.generation
    || taskId !== surface.taskId
  ) return null;
  if (!response || response.code !== 0 || !response.data) {
    setDraftStatus(surface, AUTOSAVE_STATUSES.IDLE, '');
    return null;
  }
  const draft = response.data;
  surface.revision = Number(draft.revision) || 0;
  surface.remote = draft;
  surface.conflictLocal = null;
  surface.generation = autosaveNewGeneration();
  if (draft.status === 'DISCARDED' || draft.status === 'SUBMITTED') {
    // 生命周期墓碑不恢复旧正文；保留revision，界面回到当前正式内容。
    if (surface.reset) surface.reset();
    surface.generation.lastSnapshot = surface.serialize();
    if (draft.status === 'SUBMITTED') {
      setDraftStatus(
        surface, AUTOSAVE_STATUSES.SUBMITTED,
        draft.submitted_to_id ? `已提交为 ${draft.submitted_to_id}` : '',
      );
    } else {
      setDraftStatus(surface, AUTOSAVE_STATUSES.IDLE, '');
    }
    return draft;
  }
  surface.baseArtifactId = draft.base_artifact_id || '';
  surface.baseVersion = draft.base_version || 0;
  // ACTIVE/STALE内容是本世代基线；恢复后无修改不得伪造一次用户编辑。
  if (typeof surface.hydrate === 'function') surface.hydrate(draft.content_json || {});
  surface.generation.lastSnapshot = surface.serialize();
  if (draft.status === 'STALE') {
    setDraftStatus(surface, AUTOSAVE_STATUSES.STALE, draft.stale_reason || '上游正式版本已变化');
  } else {
    setDraftStatus(surface, AUTOSAVE_STATUSES.SAVED, `v${draft.revision}`);
  }
  return draft;
}

function scheduleDraftSave(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface) return;
  // 冲突后停止自动保存，避免循环覆盖。
  if (surface.status === AUTOSAVE_STATUSES.CONFLICT) return;
  clearTimeout(surface.timer);
  setDraftStatus(surface, AUTOSAVE_STATUSES.DIRTY, '');
  surface.timer = setTimeout(() => { runDraftSave(draftKey); }, AUTOSAVE_DEBOUNCE_MS);
}

function draftPayload(surface, snapshot, revision) {
  return {
    object_type: surface.objectType,
    object_id: surface.objectId,
    stage_no: surface.stageNo,
    base_artifact_id: surface.baseArtifactId,
    base_version: surface.baseVersion,
    revision,
    content: snapshot,
  };
}

async function runDraftSave(draftKey, options = {}) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface || !surface.taskId) return null;
  if (surface.status === AUTOSAVE_STATUSES.CONFLICT && !options.force) return;
  const generation = surface.generation;
  if (generation.inFlight) {
    generation.queued = true;
    return generation.promise;
  }
  const snapshot = surface.serialize();
  if (!options.force && generation.lastSnapshot
      && sameDraftContent(generation.lastSnapshot, snapshot)) {
    // 无真实变化，不得伪造一次用户编辑，也不得递增 revision。
    return;
  }
  generation.inFlight = true;
  generation.promise = (async () => {
    setDraftStatus(surface, AUTOSAVE_STATUSES.SAVING, '');
    // 发送时同步预留revision：pagehide与并发请求不会撞版本。
    const revision = surface.revision + 1;
    surface.revision = revision;
    try {
      const response = await apiSaveAutosaveDraft(
        surface.taskId, draftKey, draftPayload(surface, snapshot, revision),
      );
      if (generation !== surface.generation) return null;
      if (response.code !== 0) {
        if (response.data && response.data.conflict) {
          handleDraftConflict(surface, snapshot, response);
          return response;
        }
        setDraftStatus(surface, AUTOSAVE_STATUSES.FAILED, response.msg || '未知错误', true);
        return response;
      }
      const storedRevision = Number(response.data && response.data.revision);
      if (Number.isFinite(storedRevision) && storedRevision > surface.revision) {
        surface.revision = storedRevision;
      }
      generation.lastSnapshot = snapshot;
      surface.remote = response.data || null;
      setDraftStatus(
        surface,
        AUTOSAVE_STATUSES.SAVED,
        'v' + surface.revision + ' · ' + new Date().toLocaleTimeString(),
      );
      return response;
    } catch (error) {
      if (generation !== surface.generation) return null;
      setDraftStatus(
        surface,
        AUTOSAVE_STATUSES.FAILED,
        '无法连接后端，草稿内容仍保留在本页',
        true,
      );
      return null;
    } finally {
      generation.inFlight = false;
      generation.promise = null;
      if (generation.queued && generation === surface.generation) {
        generation.queued = false;
        clearTimeout(surface.timer);
        surface.timer = setTimeout(
          () => { runDraftSave(draftKey); },
          AUTOSAVE_DEBOUNCE_MS,
        );
      }
    }
  })();
  return generation.promise;
}

async function flushDraft(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface || !surface.taskId) return null;
  clearTimeout(surface.timer);
  surface.timer = null;
  let response = await runDraftSave(draftKey);
  if (autosaveSurfaces.get(draftKey) !== surface) return response;
  const latest = surface.serialize();
  if (
    surface.status !== AUTOSAVE_STATUSES.CONFLICT
    && (!surface.generation.lastSnapshot
      || !sameDraftContent(surface.generation.lastSnapshot, latest))
  ) {
    surface.generation.queued = false;
    clearTimeout(surface.timer);
    surface.timer = null;
    response = await runDraftSave(draftKey);
  }
  return response;
}

function flushDraftOnExit(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface || !surface.taskId) return;
  if (surface.status === AUTOSAVE_STATUSES.CONFLICT) return;
  const snapshot = surface.serialize();
  if (surface.generation.lastSnapshot
      && sameDraftContent(surface.generation.lastSnapshot, snapshot)) return;
  // pagehide无法等待回包，先占用更高revision；
  // 仍在途的普通保存版本更低，注定被服务端拒绝。
  const revision = surface.revision + 1;
  surface.revision = revision;
  try {
    fetch(
      API_BASE + '/api/v1/console/tasks/' + encodeURIComponent(surface.taskId)
      + '/autosave-drafts/' + encodeURIComponent(draftKey),
      {
        method: 'PUT',
        keepalive: true,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draftPayload(surface, snapshot, revision)),
      },
    ).catch(() => {});
  } catch (_) {
    // 页面关闭前的末次保存失败不得影响正式论文状态。
  }
}

async function flushAllDrafts() {
  const keys = [...autosaveSurfaces.keys()];
  for (const draftKey of keys) {
    await flushDraft(draftKey);
  }
}

function flushAllDraftsOnExit() {
  autosaveSurfaces.forEach((surface, draftKey) => {
    clearTimeout(surface.timer);
    flushDraftOnExit(draftKey);
  });
}
window.addEventListener('pagehide', flushAllDraftsOnExit);


/* ---------------- 冲突：由用户决定，绝不自动采用最后写入者 ---------------- */

function handleDraftConflict(surface, localSnapshot, response) {
  surface.conflictLocal = localSnapshot;
  surface.remote = (response.data && response.data.remote) || surface.remote;
  setDraftStatus(surface, AUTOSAVE_STATUSES.CONFLICT, response.msg || '另一端已保存更新内容');
}

function reportDraftConflict(draftKey, response) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface) return;
  handleDraftConflict(surface, surface.serialize(), response || {});
}

function hideDraftConflict(surface) {
  const host = surface.conflictHost;
  if (!host) return;
  host.textContent = '';
  host.hidden = true;
}

function showDraftConflict(surface) {
  const host = surface.conflictHost;
  if (!host) return;
  host.textContent = '';
  host.hidden = false;
  const remote = surface.remote || {};
  host.append(
    autosaveElement('div', 'autosave-conflict-title', surface.label + '在另一页面已有更新'),
    autosaveElement(
      'div', 'wb-card-meta',
      '服务端 revision ' + (remote.revision != null ? remote.revision : '未知')
      + ' · 更新时间 ' + (remote.updated_at || '未知')
      + ' · base_version ' + (remote.base_version != null ? remote.base_version : '未知')
      + '；本地 revision ' + surface.revision,
    ),
  );
  const preview = autosaveElement('div', 'autosave-conflict-grid');
  preview.append(
    buildDraftPreview('本地未保存内容', surface.conflictLocal),
    buildDraftPreview('服务端已保存内容', null, true),
  );
  host.append(preview);

  const actions = autosaveElement('div', 'wb-card-actions');
  actions.append(
    conflictAction('使用服务端版', () => {
      useRemoteDraft(surface);
    }),
    conflictAction('确认使用本地版', () => saveLocalOverRemote(surface)),
    conflictAction('两者都保留', () => keepLocalAsConflictCopy(surface)),
  );
  host.append(actions);
  host.append(autosaveElement(
    'div', 'wb-card-meta',
    '冲突不会自动合并，也不会自动采用最后写入者；请选择一种处理方式。',
  ));
}

function conflictAction(label, handler) {
  const button = autosaveElement('button', 'btn btn-secondary btn-sm', label);
  button.type = 'button';
  button.addEventListener('click', handler);
  return button;
}

function buildDraftPreview(label, content, isRemote) {
  const column = autosaveElement('section', 'autosave-conflict-column');
  column.append(autosaveElement('h4', null, label));
  if (isRemote) {
    column.append(autosaveElement(
      'div', 'wb-card-meta',
      '服务端列表与冲突响应只返回元数据以保护正文；'
      + '选择“使用服务端版”后会按授权重新加载完整内容。',
    ));
    return column;
  }
  const text = typeof content === 'string'
    ? content
    : JSON.stringify(content || {}, null, 2);
  const body = autosaveElement('pre', 'autosave-preview');
  body.textContent = String(text || '').slice(0, 4000);
  column.append(body);
  return column;
}

async function useRemoteDraft(surface) {
  surface.generation.lastSnapshot = null;
  surface.conflictLocal = null;
  await loadDraft(surface.draftKey);
}

async function saveLocalOverRemote(surface) {
  const local = surface.serialize();
  const remoteRevision = Number(surface.remote?.revision);
  if (!local || !Number.isFinite(remoteRevision)) {
    setDraftStatus(surface, AUTOSAVE_STATUSES.FAILED, '无法确定服务端版本，请重新加载', true);
    return;
  }
  surface.revision = Math.max(surface.revision, remoteRevision);
  surface.conflictLocal = null;
  hideDraftConflict(surface);
  surface.generation = autosaveNewGeneration();
  surface.generation.lastSnapshot = null;
  setDraftStatus(surface, AUTOSAVE_STATUSES.DIRTY, '已确认使用本地版');
  await runDraftSave(surface.draftKey, { force: true });
}

function conflictCopyKey(draftKey) {
  const separator = String(draftKey || '').indexOf(':');
  const prefix = separator > 0 ? draftKey.slice(0, separator) : 'draft';
  const objectId = separator > 0 ? draftKey.slice(separator + 1) : 'copy';
  return prefix + ':' + objectId.slice(0, 80) + '.conflict-' + Date.now();
}

async function keepLocalAsConflictCopy(surface) {
  const conflictKey = conflictCopyKey(surface.draftKey);
  const payload = draftPayload(surface, surface.conflictLocal, 1);
  try {
    const response = await apiSaveAutosaveDraft(surface.taskId, conflictKey, payload);
    if (!response || response.code !== 0) {
      setDraftStatus(
        surface, AUTOSAVE_STATUSES.FAILED,
        response?.msg || '冲突副本保存失败，本地内容仍保留在本页', true,
      );
      return;
    }
  } catch (_) {
    setDraftStatus(
      surface, AUTOSAVE_STATUSES.FAILED,
      '冲突副本保存失败，本地内容仍保留在本页', true,
    );
    return;
  }
  surface.conflictLocal = null;
  surface.generation.lastSnapshot = null;
  await useRemoteDraft(surface);
}

/* ---------------- 生命周期 ---------------- */

async function discardDraft(draftKey) {
  const surface = autosaveSurfaces.get(draftKey);
  if (!surface || !surface.taskId) return null;
  clearTimeout(surface.timer);
  let response = null;
  try {
    response = await apiDiscardAutosaveDraft(
      surface.taskId, draftKey, surface.revision,
    );
  } catch (_) {
    response = null;
  }
  if (response && response.code === 0) {
    const tombstoneRevision = Number(response.data?.draft?.revision);
    if (Number.isFinite(tombstoneRevision)) surface.revision = tombstoneRevision;
    surface.remote = null;
    surface.conflictLocal = null;
    surface.generation = autosaveNewGeneration();
    hideDraftConflict(surface);
    if (surface.reset) surface.reset();
    setDraftStatus(surface, AUTOSAVE_STATUSES.IDLE, '');
  } else if (response?.data?.conflict) {
    handleDraftConflict(surface, surface.serialize(), response);
  } else if (response) {
    setDraftStatus(
      surface, AUTOSAVE_STATUSES.FAILED,
      response.msg || '丢弃草稿失败', true,
    );
  }
  return response;
}

function markDraftSubmitted(draftKey, submitted) {
  const surface = autosaveSurfaces.get(draftKey || '');
  if (!surface) return;
  const submittedToId = typeof submitted === 'object'
    ? submitted?.submitted_to_id
    : submitted;
  const submittedRevision = Number(
    typeof submitted === 'object' ? submitted?.revision : NaN,
  );
  if (Number.isFinite(submittedRevision) && submittedRevision > surface.revision) {
    surface.revision = submittedRevision;
  }
  clearTimeout(surface.timer);
  surface.generation.lastSnapshot = surface.serialize();
  surface.conflictLocal = null;
  hideDraftConflict(surface);
  setDraftStatus(
    surface, AUTOSAVE_STATUSES.SUBMITTED,
    submittedToId ? '已提交为 ' + submittedToId : '',
  );
}

/* 身份切换：为每个草稿面创建新世代，
   旧世代的在途请求自然结束，但只能修改旧世代自己的状态。 */
function resetAutosaveIdentity() {
  autosaveIdentityToken += 1;
  autosaveSurfaces.forEach((surface) => {
    clearTimeout(surface.timer);
    surface.timer = null;
    surface.taskId = '';
    surface.revision = 0;
    surface.remote = null;
    surface.conflictLocal = null;
    surface.generation = autosaveNewGeneration();
    hideDraftConflict(surface);
    setDraftStatus(surface, AUTOSAVE_STATUSES.IDLE, '');
  });
}

window.ThesisAutosave = Object.freeze({
  registerDraftSurface,
  unregisterDraftSurface,
  loadDraft,
  scheduleDraftSave,
  runDraftSave,
  flushDraft,
  flushAllDrafts,
  discardDraft,
  markDraftSubmitted,
  reportDraftConflict,
  showDraftConflict,
  resetAutosaveIdentity,
  surfaces: autosaveSurfaces,
  statuses: AUTOSAVE_STATUSES,
});
