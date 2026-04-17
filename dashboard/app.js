/* ═══════════════════════════════════════════════════════════════
   AGeval Dashboard — app.js
   Pure vanilla JS. No build step required.
   API key stored in memory only (never localStorage).
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── In-memory config (never persisted to localStorage) ─────────
const _cfg = {
  apiKey : sessionStorage.getItem('ageval_key') || '',
  apiBase: sessionStorage.getItem('ageval_url') || 'https://ageval-production.up.railway.app',
};

// ── Toast container ─────────────────────────────────────────────
const _toastEl = Object.assign(document.createElement('div'), { className: 'toast-container' });
document.body.appendChild(_toastEl);

function toast(msg, type = '') {
  const el = Object.assign(document.createElement('div'), {
    className: `toast ${type}`,
    textContent: msg,
  });
  _toastEl.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── API client ──────────────────────────────────────────────────
async function apiGet(path) {
  if (!_cfg.apiKey) throw new Error('No API key set. Click ⚙ Settings to connect.');
  const res = await fetch(`${_cfg.apiBase}${path}`, {
    headers: { Authorization: `Bearer ${_cfg.apiKey}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Navigation ──────────────────────────────────────────────────
let _currentView = 'episodes';

function navigate(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const viewEl = document.getElementById(`view-${view}`);
  const navEl  = document.getElementById(`nav-${view}`);

  if (viewEl) viewEl.classList.add('active');
  if (navEl)  navEl.classList.add('active');

  _currentView = view;

  if (view === 'episodes') loadEpisodes();
}

// ── Settings modal ──────────────────────────────────────────────
function openSettings() {
  document.getElementById('settingsApiKey').value = _cfg.apiKey;
  document.getElementById('settingsApiUrl').value = _cfg.apiBase;
  document.getElementById('settingsModal').classList.add('open');
  document.getElementById('settingsBackdrop').classList.add('open');
}

function closeSettings() {
  document.getElementById('settingsModal').classList.remove('open');
  document.getElementById('settingsBackdrop').classList.remove('open');
}

function saveSettings() {
  _cfg.apiKey  = document.getElementById('settingsApiKey').value.trim();
  _cfg.apiBase = document.getElementById('settingsApiUrl').value.trim().replace(/\/$/, '');
  // Store in sessionStorage so it survives page refresh but not a new tab
  sessionStorage.setItem('ageval_key', _cfg.apiKey);
  sessionStorage.setItem('ageval_url', _cfg.apiBase);
  closeSettings();
  checkConnection();
}

// ── Connection check ────────────────────────────────────────────
async function checkConnection() {
  const dot  = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  try {
    const health = await fetch(`${_cfg.apiBase}/health`).then(r => r.json());
    if (health.status === 'ok') {
      dot.className  = 'status-dot connected';
      text.textContent = 'Connected';
      loadEpisodes();
      return;
    }
  } catch {}
  dot.className  = 'status-dot error';
  text.textContent = 'Offline';
}

// ── Helpers ─────────────────────────────────────────────────────
function outcomeClass(o) {
  return o === 'success' ? 'success' : o === 'failure' ? 'danger' : o === 'partial' ? 'partial' : 'dim';
}

function scoreColor(s) {
  if (s >= 0.8) return '#22c55e';
  if (s >= 0.5) return '#f59e0b';
  return '#ef4444';
}

function scoreBar(score) {
  const pct = Math.round((score || 0) * 100);
  const color = scoreColor(score || 0);
  return `
    <div class="score-wrap">
      <div class="score-bar-bg">
        <div class="score-bar-fill" style="width:${pct}%;background:${color}"></div>
      </div>
      <span class="score-text">${pct}%</span>
    </div>`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function fmtLatency(ms) {
  if (!ms) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function jsonPreview(val) {
  if (val == null) return '<span style="color:var(--text-muted)">null</span>';
  const txt = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
  return `<div class="json-viewer">${escHtml(txt.slice(0, 400))}${txt.length > 400 ? '\n…' : ''}</div>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function loading(msg = 'Loading…') {
  return `<div class="loading-center"><div class="spinner"></div>${msg}</div>`;
}

// ── Episodes list ───────────────────────────────────────────────
let _episodes = [];
let _agentIds = new Set();

async function loadEpisodes() {
  const tableEl = document.getElementById('episodesTable');
  tableEl.innerHTML = loading();

  try {
    const agentFilter = document.getElementById('agentFilter')?.value || '';
    let path = `/episodes?limit=50`;
    if (agentFilter) path += `&agent_id=${encodeURIComponent(agentFilter)}`;

    const data = await apiGet(path);
    _episodes = data.episodes || [];

    // Collect agent IDs for filter dropdown
    _episodes.forEach(e => _agentIds.add(e.agent_id));
    _refreshAgentFilter();

    renderStats(_episodes);
    renderEpisodesTable(_episodes);
  } catch (err) {
    tableEl.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
    if (err.message.includes('API key')) openSettings();
  }
}

function _refreshAgentFilter() {
  const sel = document.getElementById('agentFilter');
  if (!sel) return;
  const curr = sel.value;
  const agents = [..._agentIds].sort();
  sel.innerHTML = '<option value="">All agents</option>' +
    agents.map(a => `<option value="${escHtml(a)}"${a===curr?' selected':''}>${escHtml(a)}</option>`).join('');
}

function renderStats(eps) {
  const total   = eps.length;
  const success = eps.filter(e => e.outcome === 'success').length;
  const failed  = eps.filter(e => e.outcome === 'failure').length;
  const avgLatency = eps.reduce((s, e) => s + (e.total_latency_ms || 0), 0) / (total || 1);

  document.getElementById('statsRow').innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total Episodes</div>
      <div class="stat-value">${total}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Success</div>
      <div class="stat-value success">${success}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Failed</div>
      <div class="stat-value danger">${failed}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg Latency</div>
      <div class="stat-value">${fmtLatency(Math.round(avgLatency))}</div>
    </div>
  `;
}

function renderEpisodesTable(eps) {
  const tableEl = document.getElementById('episodesTable');
  if (!eps.length) {
    tableEl.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><p>No episodes yet.<br>Connect your agent and run a task.</p></div>`;
    return;
  }

  tableEl.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Episode ID</th>
          <th>Agent</th>
          <th>Task</th>
          <th>Outcome</th>
          <th>Steps</th>
          <th>Latency</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        ${eps.map(e => `
          <tr onclick="openDetail('${escHtml(e.episode_id)}')">
            <td class="font-mono" style="color:var(--accent)">${escHtml(e.episode_id)}</td>
            <td>${escHtml(e.agent_id || '—')}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(e.task || '—')}</td>
            <td><span class="badge badge-${outcomeClass(e.outcome)}">${e.outcome || 'pending'}</span></td>
            <td>${e.total_steps ?? '—'}</td>
            <td>${fmtLatency(e.total_latency_ms)}</td>
            <td>${fmtDate(e.created_at)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// ── Episode detail ──────────────────────────────────────────────
let _detailEpisodeId = null;

async function openDetail(episodeId) {
  _detailEpisodeId = episodeId;
  navigate('detail');

  const content = document.getElementById('detailContent');
  content.innerHTML = loading('Loading episode…');

  try {
    const [detail, jobStatus] = await Promise.allSettled([
      apiGet(`/episodes/${episodeId}`),
      apiGet(`/jobs/${episodeId}/status`),
    ]);

    const ep    = detail.status === 'fulfilled' ? detail.value.episode : null;
    const steps = detail.status === 'fulfilled' ? detail.value.steps   : [];
    const scores= detail.status === 'fulfilled' ? detail.value.scores  : [];
    const job   = jobStatus.status === 'fulfilled' ? jobStatus.value : null;

    if (!ep) throw new Error('Episode not found');

    renderDetail(ep, steps, scores, job);
  } catch (err) {
    content.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
}

function renderDetail(ep, steps, scores, job) {
  const content = document.getElementById('detailContent');

  const rulesScore = scores.find(s => s.scorer === 'rules');
  const judgeScore = scores.find(s => s.scorer === 'llm_judge');

  content.innerHTML = `
    <div style="margin-bottom:16px">
      <h1 class="view-title" style="font-size:18px">${escHtml(ep.episode_id)}</h1>
      <p class="view-subtitle">${escHtml(ep.task || 'No task specified')}</p>
    </div>

    <div class="detail-grid">
      <!-- Left: Steps timeline -->
      <div>
        <div class="card" style="margin-bottom:16px">
          <div class="card-header">
            <span class="card-title">Step Timeline</span>
            <span class="badge badge-${outcomeClass(ep.outcome)}">${ep.outcome || 'pending'}</span>
          </div>
          <div class="step-timeline" id="stepTimeline">
            ${renderSteps(steps)}
          </div>
        </div>

        ${job ? `
        <div class="card">
          <div class="card-header"><span class="card-title">Merge Job</span>
            <span class="badge badge-${job.status === 'done' ? 'success' : job.status === 'failed' ? 'danger' : 'dim'}">${escHtml(job.status)}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Retry count</span>
            <span class="detail-meta-value">${job.retry_count ?? 0}</span>
          </div>
          ${job.error_message ? `<div class="detail-meta-item"><span class="detail-meta-label">Error</span><span class="detail-meta-value" style="color:var(--danger)">${escHtml(job.error_message)}</span></div>` : ''}
        </div>` : ''}
      </div>

      <!-- Right: Meta + Scores -->
      <div>
        <div class="card" style="margin-bottom:16px">
          <div class="card-header"><span class="card-title">Episode Info</span></div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Agent</span>
            <span class="detail-meta-value">${escHtml(ep.agent_id)}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Steps</span>
            <span class="detail-meta-value">${ep.total_steps ?? steps.length}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Total Latency</span>
            <span class="detail-meta-value">${fmtLatency(ep.total_latency_ms)}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Created</span>
            <span class="detail-meta-value">${fmtDate(ep.created_at)}</span>
          </div>
        </div>

        ${rulesScore ? `
        <div class="card" style="margin-bottom:16px">
          <div class="card-header">
            <span class="card-title">Rule-Based Score</span>
            <span style="font-family:var(--mono);font-size:13px;color:${scoreColor(rulesScore.score)};font-weight:600">${Math.round(rulesScore.score*100)}%</span>
          </div>
          <div class="score-breakdown">
            ${Object.entries(rulesScore.breakdown || {}).map(([k,v]) => `
              <div class="breakdown-item">
                <span class="breakdown-label">${k.replace(/_/g,' ')}</span>
                ${scoreBar(v)}
              </div>
            `).join('')}
          </div>
        </div>` : ''}

        ${judgeScore ? `
        <div class="card">
          <div class="card-header">
            <span class="card-title">LLM Judge Score</span>
            <span style="font-family:var(--mono);font-size:13px;color:${scoreColor(judgeScore.score)};font-weight:600">${Math.round(judgeScore.score*100)}%</span>
          </div>
          <div class="score-breakdown">
            ${['task_completion','reasoning_quality','error_handling','output_quality'].map(k => `
              <div class="breakdown-item">
                <span class="breakdown-label">${k.replace(/_/g,' ')}</span>
                ${scoreBar(judgeScore.breakdown?.[k])}
              </div>
            `).join('')}
          </div>
          ${judgeScore.breakdown?.reasoning ? `
          <div style="padding:12px 20px;border-top:1px solid var(--border)">
            <div class="form-label" style="margin-bottom:6px">Judge reasoning</div>
            <p style="font-size:12px;color:var(--text-muted);font-style:italic">${escHtml(judgeScore.breakdown.reasoning)}</p>
          </div>` : ''}
        </div>` : ''}

        ${!rulesScore && !judgeScore ? `
        <div class="card">
          <div class="loading-center" style="padding:24px">
            <div class="spinner"></div>
            Scoring in progress…
          </div>
        </div>` : ''}
      </div>
    </div>
  `;
}

function renderSteps(steps) {
  if (!steps.length) return '<div class="empty-state" style="padding:24px"><p>No steps recorded.</p></div>';

  return steps.map((s, i) => `
    <div class="step-item" id="step-${i}" onclick="toggleStep(${i})">
      <div class="step-indicator">
        <div class="step-dot ${s.success ? 'success' : 'fail'}"></div>
        ${i < steps.length - 1 ? '<div class="step-line"></div>' : ''}
      </div>
      <div class="step-body">
        <div class="step-tool">${escHtml(s.tool_name)}</div>
        <div class="step-meta">
          <span>${s.success ? '✓ success' : `✗ ${s.error_category || 'failed'}`}</span>
          ${s.latency_ms != null ? `<span>⏱ ${fmtLatency(s.latency_ms)}</span>` : ''}
          <span style="color:var(--text-muted)">step ${s.step_index}</span>
          ${s.is_recoverable === false ? '<span style="color:var(--danger)">not recoverable</span>' : ''}
        </div>
        ${s.reasoning ? `<div class="step-reasoning">${escHtml(s.reasoning)}</div>` : ''}
        ${s.error_message ? `
        <div class="step-reasoning" style="border-left-color:var(--danger);display:block">
          ${escHtml(s.error_message)}
        </div>` : ''}
        ${s.tool_output != null ? `<div class="step-reasoning" id="step-output-${i}" style="display:none">${jsonPreview(s.tool_output)}</div>` : ''}
      </div>
    </div>
  `).join('');
}

function toggleStep(i) {
  const el = document.getElementById(`step-${i}`);
  const out = document.getElementById(`step-output-${i}`);
  if (el) el.classList.toggle('expanded');
  if (out) out.style.display = out.style.display === 'none' ? 'block' : 'none';
}

// ── Compare ─────────────────────────────────────────────────────
function setupCompare() {
  navigate('compare');
  if (_detailEpisodeId) {
    document.getElementById('compareEpA').value = _detailEpisodeId;
  }
}

async function runCompare() {
  const epA = document.getElementById('compareEpA').value.trim();
  const epB = document.getElementById('compareEpB').value.trim();
  const result = document.getElementById('compareResult');

  if (!epA || !epB) { toast('Enter both episode IDs', 'error'); return; }

  result.innerHTML = loading('Fetching episodes…');

  try {
    const data = await apiGet(`/compare?episode_a=${encodeURIComponent(epA)}&episode_b=${encodeURIComponent(epB)}`);
    renderCompare(data);
  } catch (err) {
    result.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
}

function renderCompare(data) {
  const { episode_a, episode_b, steps_a, steps_b } = data;

  document.getElementById('compareResult').innerHTML = `
    <div class="compare-grid">
      ${renderEpisodePanel('A', episode_a, steps_a)}
      ${renderEpisodePanel('B', episode_b, steps_b)}
    </div>
  `;
}

function renderEpisodePanel(label, ep, steps) {
  if (!ep) return `<div class="card"><div class="loading-center">Episode ${label} not found</div></div>`;
  return `
    <div class="card">
      <div class="card-header">
        <span class="card-title">Episode ${label}</span>
        <span class="badge badge-${outcomeClass(ep.outcome)}">${ep.outcome || '?'}</span>
      </div>
      <div class="detail-meta-item">
        <span class="detail-meta-label">ID</span>
        <span class="detail-meta-value font-mono">${escHtml(ep.episode_id)}</span>
      </div>
      <div class="detail-meta-item">
        <span class="detail-meta-label">Task</span>
        <span class="detail-meta-value">${escHtml(ep.task || '—')}</span>
      </div>
      <div class="detail-meta-item">
        <span class="detail-meta-label">Steps / Latency</span>
        <span class="detail-meta-value">${ep.total_steps ?? steps.length} steps · ${fmtLatency(ep.total_latency_ms)}</span>
      </div>
      <div style="padding:0;max-height:400px;overflow-y:auto" class="step-timeline">
        ${steps.map((s, i) => `
          <div class="step-item" style="cursor:default">
            <div class="step-indicator">
              <div class="step-dot ${s.success ? 'success' : 'fail'}"></div>
              ${i < steps.length - 1 ? '<div class="step-line"></div>' : ''}
            </div>
            <div class="step-body">
              <div class="step-tool">${escHtml(s.tool_name)}</div>
              <div class="step-meta">
                <span>${s.success ? '✓' : '✗'}</span>
                ${s.latency_ms != null ? `<span>${fmtLatency(s.latency_ms)}</span>` : ''}
              </div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

// ── Recall ──────────────────────────────────────────────────────
async function runRecall() {
  const query   = document.getElementById('recallQuery').value.trim();
  const outcome = document.getElementById('recallOutcome').value;
  const k       = document.getElementById('recallK').value;
  const result  = document.getElementById('recallResult');

  if (!query) { toast('Enter a task description to search', 'error'); return; }

  result.innerHTML = loading('Searching episode memory…');

  try {
    let path = `/recall?task=${encodeURIComponent(query)}&k=${k}`;
    if (outcome) path += `&outcome=${encodeURIComponent(outcome)}`;

    const data = await apiGet(path);
    const eps  = data.episodes || [];

    if (!eps.length) {
      result.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>No similar episodes found. Run more agent tasks to build memory.</p></div>`;
      return;
    }

    result.innerHTML = eps.map(e => `
      <div class="recall-card" onclick="openDetail('${escHtml(e.episode_id)}')">
        <div class="recall-task">${escHtml(e.task || e.episode_id)}</div>
        <div class="recall-meta">
          <span class="badge badge-${outcomeClass(e.outcome)}">${e.outcome || '?'}</span>
          <span>${escHtml(e.agent_id || '—')}</span>
          <span>${e.total_steps ?? '?'} steps</span>
          ${e.similarity != null ? `<span class="similarity-badge">⬡ ${Math.round(e.similarity * 100)}% match</span>` : ''}
        </div>
      </div>
    `).join('');
  } catch (err) {
    result.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
}

// ── Find similar from detail view ───────────────────────────────
async function findSimilar() {
  if (!_detailEpisodeId) return;
  navigate('recall');
  document.getElementById('recallQuery').value = '';
  const result = document.getElementById('recallResult');
  result.innerHTML = loading('Finding similar episodes…');

  try {
    const data = await apiGet(`/similar?episode_id=${encodeURIComponent(_detailEpisodeId)}&k=5`);
    const eps  = data.similar || [];

    if (!eps.length) {
      result.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>No similar episodes found yet. Embeddings may not be generated.</p></div>`;
      return;
    }

    result.innerHTML = `
      <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">Episodes similar to <code style="font-family:var(--mono)">${escHtml(_detailEpisodeId)}</code></p>
      ${eps.map(e => `
        <div class="recall-card" onclick="openDetail('${escHtml(e.episode_id)}')">
          <div class="recall-task">${escHtml(e.task || e.episode_id)}</div>
          <div class="recall-meta">
            <span class="badge badge-${outcomeClass(e.outcome)}">${e.outcome || '?'}</span>
            <span>${e.total_steps ?? '?'} steps</span>
            ${e.similarity != null ? `<span class="similarity-badge">⬡ ${Math.round(e.similarity * 100)}% match</span>` : ''}
          </div>
        </div>
      `).join('')}
    `;
  } catch (err) {
    result.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
}

// ── Boot ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkConnection();
  if (!_cfg.apiKey) {
    setTimeout(openSettings, 300);
  }
});
