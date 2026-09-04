/* Evidence and argument overview module. Loaded before app.js; dependencies resolve at runtime. */
(() => {
  let requestVersion = 0;

  async function apiTaskSources(taskId) {
    return apiGet(`/api/v1/console/tasks/${taskId}/sources`);
  }

  async function apiEvidenceAudit(taskId) {
    return apiGet(`/api/v1/console/tasks/${taskId}/evidence-audit`);
  }

  function renderFoundation(data) {
    const rows = data.evidence_table || [];
    const missing = data.missing_artifacts || [];
    const summary = `<div class="wb-card">
      <div class="wb-card-title">研究规范快照</div>
      <div class="wb-card-meta">Hash ${escapeHtml2((data.canon_hash || '').slice(0, 12))} · ${data.artifact_refs?.length || 0} 个已批准产物 · ${data.source_refs?.length || 0} 个来源 · ${data.verified_result_ids?.length || 0} 条已核验结果标识</div>
      <div class="wb-card-meta">${data.can_write ? '当前证据表可供写作门禁使用。' : '当前快照仍有阻断项，不能据此生成正文。'}</div>
      ${missing.length ? `<div class="wb-card-meta">缺少：${escapeHtml2(missing.join('、'))}</div>` : ''}
    </div>`;
    if (!rows.length) {
      return summary + '<div class="wb-empty">批准论证图后，这里会显示不含摘录正文的证据表。</div>';
    }
    const body = rows.map(row => `<tr>
      <th scope="row">${escapeHtml2(row.claim_key)}</th>
      <td>${escapeHtml2(row.section_id || '未分节')} · ${escapeHtml2(row.text)}</td>
      <td>${escapeHtml2(row.epistemic_intent)}</td>
      <td><span class="wb-status ${wbStatusClass(row.evidence_state)}">${escapeHtml2(row.evidence_state)}</span></td>
      <td>${escapeHtml2(row.verification_strength)}</td>
      <td>${escapeHtml2(row.risk_level)}</td>
    </tr>`).join('');
    return summary + `<div class="wb-card academic-foundation-table-wrap">
      <table class="academic-foundation-table">
        <caption class="sr-only">当前论文的主张证据状态表</caption>
        <thead><tr><th scope="col">主张键</th><th scope="col">主张</th><th scope="col">意图</th><th scope="col">证据状态</th><th scope="col">核验强度</th><th scope="col">风险</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
  }

  async function loadEvidencePanel() {
    const claimBox = document.getElementById('claim-audit-list');
    const sourceBox = document.getElementById('source-ledger-list');
    const mapBox = document.getElementById('argument-map-list');
    const foundationBox = document.getElementById('academic-foundation-list');
    const live = document.getElementById('evidence-live');
    if (!claimBox || !sourceBox || !mapBox || !foundationBox) return;
    if (!currentSession) {
      claimBox.innerHTML = '<div class="wb-empty">选择论文任务后查看证据。</div>';
      sourceBox.innerHTML = '';
      mapBox.innerHTML = '';
      foundationBox.innerHTML = '';
      return;
    }
    const taskId = currentSession;
    const version = ++requestVersion;
    claimBox.setAttribute('aria-busy', 'true');
    foundationBox.setAttribute('aria-busy', 'true');
    const [auditResponse, sourceResponse, mapResponse, foundationResponse, progress] = await Promise.all([
      apiEvidenceAudit(taskId), apiTaskSources(taskId), apiArgumentMaps(taskId),
      apiAcademicFoundation(taskId),
      apiSessionProgress(taskId),
    ]);
    if (version !== requestVersion || taskId !== currentSession) return;
    claimBox.removeAttribute('aria-busy');
    foundationBox.removeAttribute('aria-busy');
    foundationBox.innerHTML = foundationResponse.code === 0
      ? renderFoundation(foundationResponse.data || {})
      : `<div class="wb-error">${escapeHtml2(foundationResponse.msg || '研究规范快照加载失败')}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" data-foundation-retry>重试</button></div></div>`;
    foundationBox.querySelector('[data-foundation-retry]')?.addEventListener('click', loadEvidencePanel);
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
      const failedCount = [auditResponse, sourceResponse, mapResponse, foundationResponse]
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
