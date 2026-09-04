/* Project memory feature module. Loaded before app.js; dependencies resolve at runtime. */
async function apiProjectMemories(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/memory`);
}
async function apiCreateProjectMemory(taskId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/memory`, payload);
}
async function apiReviewProjectMemory(taskId, artifactId, approved, reason = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/memory/${artifactId}/review`, {
    approved, reason, actor: 'author',
  });
}

let memoryRevisionBase = null;
const PROJECT_MEMORY_DRAFT_KEY = 'project-memory:new';
const STOPPING_POLICY_ERROR = '请按字段范围填写自动修订停止规则。';
const STOPPING_POLICY_FIELDS = [
  'memory-max-rounds', 'memory-plateau-rounds', 'memory-min-improvement',
];

async function ensureProjectMemoryAutosave() {
  if (!currentSession || !window.ThesisAutosave?.registerDraftSurface) return null;
  const existing = window.ThesisAutosave.surfaces.get(PROJECT_MEMORY_DRAFT_KEY);
  if (existing?.taskId === currentSession) return existing;
  const form = document.getElementById('memory-form');
  const surface = window.ThesisAutosave.registerDraftSurface({
    draftKey: PROJECT_MEMORY_DRAFT_KEY,
    taskId: currentSession,
    objectType: 'PROJECT_MEMORY_FORM',
    objectId: 'new',
    stageNo: 0,
    label: '项目记忆',
    statusEl: document.getElementById('memory-autosave-status'),
    conflictHost: document.getElementById('memory-autosave-conflict'),
    serialize: () => buildProjectMemoryPayload(),
    hydrate: payload => fillProjectMemoryForm(payload || {}, '', '', { focus: false }),
    reset: () => {
      memoryRevisionBase = null;
      form?.reset();
      document.getElementById('memory-submit').textContent = '生成待审批版本';
    },
  });
  if (form && !form.dataset.autosaveBound) {
    form.dataset.autosaveBound = '1';
    const schedule = () => {
      window.ThesisAutosave.scheduleDraftSave(PROJECT_MEMORY_DRAFT_KEY);
    };
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
  }
  STOPPING_POLICY_FIELDS.forEach((id) => {
    const input = document.getElementById(id);
    if (!input || input.dataset.validationBound) return;
    input.dataset.validationBound = '1';
    input.addEventListener('input', () => {
      if (input.checkValidity()) input.removeAttribute('aria-invalid');
      const error = document.getElementById('memory-error');
      const allValid = STOPPING_POLICY_FIELDS.every(
        fieldId => document.getElementById(fieldId).checkValidity(),
      );
      if (allValid && error.textContent === STOPPING_POLICY_ERROR) {
        error.textContent = '';
      }
    });
  });
  await window.ThesisAutosave.loadDraft(PROJECT_MEMORY_DRAFT_KEY);
  return surface;
}

function splitMemoryDecision(line) {
  const parts = String(line || '').split('|');
  return { text: (parts.shift() || '').trim(), rationale: parts.join('|').trim() };
}

function fillProjectMemoryForm(
  memory, version = '', artifactId = '', options = { focus: true },
) {
  const style = memory?.writing_style || {};
  const stopping = memory?.stopping_policy || {};
  memoryRevisionBase = memory || null;
  document.getElementById('memory-questions').value = (memory?.research_questions || []).join('\n');
  document.getElementById('memory-scope-boundaries').value = (memory?.scope_boundaries || []).join('\n');
  document.getElementById('memory-forbidden-claims').value = (memory?.forbidden_claims || []).join('\n');
  document.getElementById('memory-unresolved-claims').value = (memory?.unresolved_claims || []).join('\n');
  document.getElementById('memory-decisions').value = (memory?.decisions || [])
    .map(item => item.rationale ? `${item.text} | ${item.rationale}` : item.text).join('\n');
  document.getElementById('memory-feedback').value = (memory?.supervisor_feedback || [])
    .map(item => item.text).join('\n');
  document.getElementById('memory-terms').value = (memory?.terminology || [])
    .map(item => `${item.term}=${item.preferred_form}`).join('\n');
  document.getElementById('memory-language').value = style.language || 'zh-CN';
  document.getElementById('memory-tone').value = style.tone || '客观、审慎、学术';
  document.getElementById('memory-person').value = style.person || '避免不必要的第一人称';
  document.getElementById('memory-tense').value = style.tense || '按学科惯例使用';
  document.getElementById('memory-citation-style').value = style.citation_style || 'GB/T 7714-2015';
  document.getElementById('memory-constraints').value = (style.constraints || []).join('\n');
  document.getElementById('memory-max-rounds').value = stopping.max_revision_rounds ?? 3;
  document.getElementById('memory-plateau-rounds').value = stopping.plateau_rounds ?? 2;
  document.getElementById('memory-min-improvement').value = stopping.min_score_improvement ?? 0.5;
  document.getElementById('memory-version-note').value = version ? `基于v${version}修订` : (memory?.version_note || '');
  document.getElementById('memory-submit').textContent = version ? '生成修订版本' : '生成待审批版本';
  document.getElementById('memory-error').textContent = '';
  document.getElementById('memory-questions').removeAttribute('aria-invalid');
  const builder = document.getElementById('memory-builder');
  builder.open = true;
  const surface = window.ThesisAutosave?.surfaces?.get(PROJECT_MEMORY_DRAFT_KEY);
  if (surface && artifactId) {
    surface.baseArtifactId = artifactId;
    surface.baseVersion = Number(version) || 0;
  }
  if (options.focus !== false) document.getElementById('memory-questions').focus();
}

function buildProjectMemoryPayload() {
  const questions = valueLines('memory-questions');
  const previousDecisions = memoryRevisionBase?.decisions || [];
  const decisions = valueLines('memory-decisions').map(line => {
    const parsed = splitMemoryDecision(line);
    const previous = previousDecisions.find(item => item.text === parsed.text);
    return previous
      ? { ...previous, rationale: parsed.rationale || previous.rationale || '' }
      : { text: parsed.text, rationale: parsed.rationale, source: 'AUTHOR', active: true };
  }).filter(item => item.text);
  const previousFeedback = memoryRevisionBase?.supervisor_feedback || [];
  const supervisorFeedback = valueLines('memory-feedback').map(text => (
    previousFeedback.find(item => item.text === text) || {
      text, status: 'PENDING', response: '',
    }
  ));
  const previousTerms = memoryRevisionBase?.terminology || [];
  const terminology = valueLines('memory-terms').map(line => {
    const separator = line.indexOf('=');
    const term = (separator >= 0 ? line.slice(0, separator) : line).trim();
    const preferred = (separator >= 0 ? line.slice(separator + 1) : term).trim() || term;
    const previous = previousTerms.find(item => item.term === term);
    return previous
      ? { ...previous, preferred_form: preferred }
      : { term, preferred_form: preferred, definition: '', forbidden_aliases: [] };
  }).filter(item => item.term);
  return {
    research_questions: questions,
    scope_boundaries: valueLines('memory-scope-boundaries'),
    forbidden_claims: valueLines('memory-forbidden-claims'),
    unresolved_claims: valueLines('memory-unresolved-claims'),
    decisions,
    supervisor_feedback: supervisorFeedback,
    terminology,
    writing_style: {
      language: document.getElementById('memory-language').value,
      tone: document.getElementById('memory-tone').value.trim(),
      person: document.getElementById('memory-person').value.trim(),
      tense: document.getElementById('memory-tense').value.trim(),
      citation_style: document.getElementById('memory-citation-style').value.trim(),
      constraints: valueLines('memory-constraints'),
    },
    stopping_policy: {
      max_revision_rounds: Number(document.getElementById('memory-max-rounds').value || 3),
      plateau_rounds: Number(document.getElementById('memory-plateau-rounds').value || 2),
      min_score_improvement: Number(document.getElementById('memory-min-improvement').value || 0.5),
    },
    version_note: document.getElementById('memory-version-note').value.trim(),
  };
}

function renderProjectMemoryVersions(items) {
  const box = document.getElementById('memory-list');
  if (!items.length) {
    box.innerHTML = '<div class="wb-empty">尚未建立项目记忆。创建后需作者批准才会供Agent使用。</div>';
    return;
  }
  box.innerHTML = items.slice().reverse().map(item => {
    const memory = item.payload || {};
    const style = memory.writing_style || {};
    const questions = memory.research_questions || [];
    const boundaries = memory.scope_boundaries || [];
    const forbidden = memory.forbidden_claims || [];
    const unresolved = memory.unresolved_claims || [];
    const decisions = memory.decisions || [];
    const feedback = memory.supervisor_feedback || [];
    const terms = memory.terminology || [];
    const waiting = item.status === 'WAITING_APPROVAL';
    const revisable = ['APPROVED', 'REJECTED', 'SUPERSEDED'].includes(item.status);
    return `<article class="wb-card" data-memory-id="${escapeHtml2(item.artifact_id)}">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:start;">
        <div class="wb-card-title">项目记忆 v${item.version}</div>
        <span class="wb-status ${wbStatusClass(item.status)}">${escapeHtml2(item.status)}</span>
      </div>
      <div class="wb-card-meta">研究问题 ${questions.length} · 范围边界 ${boundaries.length} · 禁写 ${forbidden.length} · 待解决 ${unresolved.length}</div>
      <div class="wb-card-meta">决定 ${decisions.length} · 导师意见 ${feedback.length} · 术语 ${terms.length}</div>
      <div class="wb-card-meta">${escapeHtml2(style.language || '未设定')} · ${escapeHtml2(style.tone || '未设定语气')} · ${escapeHtml2(style.citation_style || '未设定引用样式')}</div>
      ${memory.version_note ? `<div class="wb-card-meta">${escapeHtml2(memory.version_note)}</div>` : ''}
      <details><summary class="wb-card-meta">查看记忆摘要</summary>
        ${questions.length ? `<ol>${questions.map(value => `<li>${escapeHtml2(value)}</li>`).join('')}</ol>` : '<div class="wb-card-meta">未设定研究问题。</div>'}
        ${boundaries.length ? `<div class="wb-card-meta">范围边界：${boundaries.slice(0, 8).map(escapeHtml2).join('；')}</div>` : ''}
        ${forbidden.length ? `<div class="wb-card-meta">禁写主张：${forbidden.slice(0, 8).map(escapeHtml2).join('；')}</div>` : ''}
        ${unresolved.length ? `<div class="wb-card-meta">待解决：${unresolved.slice(0, 8).map(escapeHtml2).join('；')}</div>` : ''}
        ${terms.length ? `<div class="wb-card-meta">术语：${terms.slice(0, 12).map(value => `${escapeHtml2(value.term)}→${escapeHtml2(value.preferred_form)}`).join('、')}</div>` : ''}
      </details>
      <div class="wb-card-actions">
        ${waiting ? '<button class="btn btn-primary btn-sm" data-memory-action="approve">批准</button><button class="btn btn-secondary btn-sm" data-memory-action="reject">驳回</button>' : ''}
        ${revisable ? '<button class="btn btn-secondary btn-sm" data-memory-action="revise">基于此版修订</button>' : ''}
      </div>
    </article>`;
  }).join('');
  box.querySelectorAll('[data-memory-action]').forEach(button => {
    button.addEventListener('click', handleProjectMemoryAction);
  });
}

async function loadProjectMemoryPanel(announce = true) {
  const box = document.getElementById('memory-list');
  if (!box) return;
  if (!currentSession) {
    box.innerHTML = '<div class="wb-empty">选择论文任务后查看项目记忆。</div>';
    return;
  }
  const taskId = currentSession;
  await ensureProjectMemoryAutosave();
  if (taskId !== currentSession) return;
  box.setAttribute('aria-busy', 'true');
  const response = await apiProjectMemories(taskId);
  if (taskId !== currentSession) return;
  box.removeAttribute('aria-busy');
  if (response.code !== 0) {
    box.innerHTML = `<div class="wb-error">${escapeHtml2(response.msg || '加载项目记忆失败')}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" id="memory-retry">重试</button></div></div>`;
    document.getElementById('memory-retry')?.addEventListener('click', () => loadProjectMemoryPanel());
    return;
  }
  const items = response.data || [];
  renderProjectMemoryVersions(items);
  if (announce) {
    const active = items.find(item => item.status === 'APPROVED');
    document.getElementById('memory-live').textContent = active
      ? `已加载 ${items.length} 个版本，当前批准版本v${active.version}`
      : `已加载 ${items.length} 个版本，尚无批准版本`;
  }
}

async function submitProjectMemoryForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const questions = document.getElementById('memory-questions');
  const error = document.getElementById('memory-error');
  if (!currentSession) {
    error.textContent = '请先选择论文任务。';
    return;
  }
  if (!valueLines('memory-questions').length) {
    questions.setAttribute('aria-invalid', 'true');
    error.textContent = '至少填写一个研究问题。';
    questions.focus();
    return;
  }
  const invalidStoppingField = STOPPING_POLICY_FIELDS
    .map(id => document.getElementById(id)).find(input => !input.checkValidity());
  if (invalidStoppingField) {
    invalidStoppingField.setAttribute('aria-invalid', 'true');
    error.textContent = STOPPING_POLICY_ERROR;
    invalidStoppingField.focus();
    return;
  }
  STOPPING_POLICY_FIELDS
    .forEach(id => document.getElementById(id).removeAttribute('aria-invalid'));
  questions.removeAttribute('aria-invalid');
  error.textContent = '';
  const submit = document.getElementById('memory-submit');
  submit.disabled = true;
  const surface = await ensureProjectMemoryAutosave();
  if (surface) {
    await window.ThesisAutosave.flushDraft(PROJECT_MEMORY_DRAFT_KEY);
    if (['conflict', 'stale', 'failed', 'saving', 'dirty'].includes(surface.status)) {
      error.textContent = '自动草稿尚未安全保存或需要处理冲突。';
      submit.disabled = false;
      return;
    }
  }
  const payload = buildProjectMemoryPayload();
  if (surface && surface.revision > 0) {
    payload.autosave_draft_key = PROJECT_MEMORY_DRAFT_KEY;
    payload.autosave_revision = surface.revision;
  }
  const response = await apiCreateProjectMemory(currentSession, payload);
  submit.disabled = false;
  if (response?.data?.conflict && surface) {
    window.ThesisAutosave.reportDraftConflict(
      PROJECT_MEMORY_DRAFT_KEY, response,
    );
    error.textContent = '正式提交基于旧草稿，请先处理冲突。';
    return;
  }
  if (response.code !== 0) {
    error.textContent = response.msg || '生成项目记忆版本失败。';
    return;
  }
  toast(response.msg);
  if (response.data?.autosave_draft) {
    window.ThesisAutosave.markDraftSubmitted(
      PROJECT_MEMORY_DRAFT_KEY, response.data.autosave_draft,
    );
    surface.baseArtifactId = response.data.artifact_id || '';
    surface.baseVersion = Number(response.data.version) || 0;
  }
  memoryRevisionBase = null;
  form.reset();
  submit.textContent = '生成待审批版本';
  document.getElementById('memory-builder').open = false;
  await loadProjectMemoryPanel();
  // 新增待审批记忆版本会改变恢复摘要里的待审批集合。
  await refreshVisibleResumeSummary();
}

async function handleProjectMemoryAction(event) {
  const button = event.currentTarget;
  const action = button.dataset.memoryAction;
  const card = button.closest('[data-memory-id]');
  const artifactId = card?.dataset.memoryId;
  if (!artifactId || !currentSession) return;
  const response = await apiProjectMemories(currentSession);
  const item = (response.data || []).find(value => value.artifact_id === artifactId);
  if (!item) {
    toast('记忆版本已变更，请刷新。');
    return;
  }
  if (action === 'revise') {
    fillProjectMemoryForm(
      item.payload || {}, item.version, item.artifact_id,
    );
    return;
  }
  let reason = '';
  if (action === 'reject') {
    const entered = window.prompt('请输入驳回原因（可取消）', '');
    if (entered === null) return;
    reason = entered.trim();
  }
  button.disabled = true;
  const reviewed = await apiReviewProjectMemory(
    currentSession, artifactId, action === 'approve', reason
  );
  toast(reviewed.code === 0 ? reviewed.msg : `审批失败：${reviewed.msg}`);
  await loadProjectMemoryPanel();
  // 记忆批准 / 驳回会改变待审批集合；失败不得伪造新状态。
  if (reviewed.code === 0) await refreshVisibleResumeSummary();
}

window.ThesisProjectMemory = Object.freeze({
  loadPanel: loadProjectMemoryPanel,
  submitForm: submitProjectMemoryForm,
});
