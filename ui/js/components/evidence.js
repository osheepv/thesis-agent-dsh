/* Evidence and argument overview module. Loaded before app.js; dependencies resolve at runtime. */
(() => {
  let requestVersion = 0;

  async function apiTaskSources(taskId) {
    return apiGet(`/api/v1/console/tasks/${taskId}/sources`);
  }

  async function apiEvidenceAudit(taskId) {
    return apiGet(`/api/v1/console/tasks/${taskId}/evidence-audit`);
  }

  async function loadEvidencePanel() {
    const claimBox = document.getElementById('claim-audit-list');
    const sourceBox = document.getElementById('source-ledger-list');
    const mapBox = document.getElementById('argument-map-list');
    const live = document.getElementById('evidence-live');
    if (!claimBox || !sourceBox || !mapBox) return;
    if (!currentSession) {
      claimBox.innerHTML = '<div class="wb-empty">选择论文任务后查看证据。</div>';
      sourceBox.innerHTML = '';
      mapBox.innerHTML = '';
      return;
    }
    const taskId = currentSession;
    const version = ++requestVersion;
    claimBox.setAttribute('aria-busy', 'true');
    const [auditResponse, sourceResponse, mapResponse, progress] = await Promise.all([
      apiEvidenceAudit(taskId), apiTaskSources(taskId), apiArgumentMaps(taskId),
      apiSessionProgress(taskId),
    ]);
    if (version !== requestVersion || taskId !== currentSession) return;
    claimBox.removeAttribute('aria-busy');
    const trustHtml = window.ThesisTrustUI.renderAssessment(
      progress?.trust_assessments?.['8'] || null,
    );
    if (auditResponse.code !== 0) {
      claimBox.innerHTML = trustHtml + `<div class="wb-error">${escapeHtml2(auditResponse.msg)}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" data-evidence-retry>重试</button></div></div>`;
      claimBox.querySelector('[data-evidence-retry]')?.addEventListener('click', loadEvidencePanel);
    } else {
      const audit = auditResponse.data || {};
      const claims = audit.claims || [];
      claimBox.innerHTML = trustHtml + `<div class="wb-card">
        <div class="wb-card-title">论断覆盖：${audit.supported_count || 0}/${audit.claim_count || 0}</div>
        <div class="wb-card-meta">未支持 ${audit.unsupported_count || 0} · 有争议 ${audit.disputed_count || 0}</div>
      </div>` + (claims.length ? claims.map(claim => `<article class="wb-card">
        <div style="display:flex;justify-content:space-between;gap:8px;"><div class="wb-card-title">${escapeHtml2(claim.text)}</div><span class="wb-status ${wbStatusClass(claim.status)}">${escapeHtml2(claim.status)}</span></div>
        <div class="wb-card-meta">${escapeHtml2(claim.section_id || '未分节')} · ${escapeHtml2(claim.claim_type || '')}</div>
        <div class="wb-card-meta">支持证据 ${(claim.supporting_evidence_ids || []).length} · 反证 ${(claim.contradicting_evidence_ids || []).length}</div>
      </article>`).join('') : '<div class="wb-empty">尚未登记论断；批准论证图后会自动出现。</div>');
    }
    const sources = sourceResponse.code === 0 ? (sourceResponse.data || []) : [];
    sourceBox.innerHTML = `<div class="kb-section-title"><span>来源账本</span><span class="count">${sources.length}</span></div>` +
      (sourceResponse.code !== 0
        ? `<div class="wb-error">${escapeHtml2(sourceResponse.msg || '来源账本加载失败')}</div>`
        : sources.length ? sources.slice(0, 100).map(source => `<article class="wb-card">
          <div class="wb-card-title">${escapeHtml2(source.title || source.doi || source.source_id)}</div>
          <div class="wb-card-meta">${escapeHtml2(source.verification_status)}${source.doi ? ` · DOI ${escapeHtml2(source.doi)}` : ''}</div>
        </article>`).join('') : '<div class="wb-empty">来源账本为空；批准环3文献后会自动登记。</div>');
    const maps = mapResponse.code === 0 ? (mapResponse.data || []) : [];
    mapBox.innerHTML = `<div class="kb-section-title"><span>论证图版本</span><span class="count">${maps.length}</span></div>` +
      (mapResponse.code !== 0
        ? `<div class="wb-error">${escapeHtml2(mapResponse.msg || '论证图加载失败')}</div>`
        : maps.length ? maps.map(map => `<article class="wb-card">
          <div style="display:flex;justify-content:space-between;gap:8px;"><div class="wb-card-title">v${map.version} ${escapeHtml2(map.payload?.title || '论证图')}</div><span class="wb-status ${wbStatusClass(map.status)}">${escapeHtml2(map.status)}</span></div>
          <div class="wb-card-meta">${(map.payload?.claims || []).length} 个论断 · ${(map.payload?.research_questions || []).length} 个研究问题</div>
        </article>`).join('') : '<div class="wb-empty">尚未创建论证图，可在环5通过 API 或 Agent 引导创建。</div>');
    if (live) {
      const failedCount = [auditResponse, sourceResponse, mapResponse]
        .filter(response => response.code !== 0).length;
      live.textContent = failedCount
        ? `证据工作台有 ${failedCount} 类数据加载失败`
        : `证据审计与 ${sources.length} 个来源已更新`;
    }
  }

  window.ThesisEvidence = Object.freeze({
    loadPanel: loadEvidencePanel,
  });
})();
