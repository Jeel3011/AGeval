/* ═══════════════════════════════════════════════════════════════
   AGeval Dashboard — app.js
   Pure vanilla JS. No build step required.
   API key stored in memory only (never localStorage).
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── In-memory config (never persisted to localStorage) ─────────
const _cfg = {
  apiKey : sessionStorage.getItem('ageval_key') || localStorage.getItem('ageval_key') || '',
  apiBase: sessionStorage.getItem('ageval_url') || localStorage.getItem('ageval_url') || 'https://ageval-production.up.railway.app',
};

// ── Global Keyboard Shortcuts ───────────────────────────────────
document.addEventListener('keydown', e => {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
  if (e.key === 'Escape') closeSettings();
  if (e.key === '/') { e.preventDefault(); document.getElementById('taskSearch')?.focus(); }
  if (e.key === 'g') {
    const nextFn = ev => {
      if (ev.key === 'h') navigate('health');
      if (ev.key === 'e') navigate('episodes');
      if (ev.key === 'c') navigate('compare');
      if (ev.key === 'r') navigate('recall');
      document.removeEventListener('keydown', nextFn);
    };
    document.addEventListener('keydown', nextFn);
    setTimeout(() => document.removeEventListener('keydown', nextFn), 1000);
  }
  if (_currentView === 'detail') {
    if (e.key === 'ArrowLeft') navigateDetail(-1);
    if (e.key === 'ArrowRight') navigateDetail(1);
  }
});

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

  if (view === 'health') loadHealth();
  if (view === 'episodes') loadEpisodes();
  if (view === 'clusters') loadClusters();
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

async function saveSettings() {
  const btn = document.getElementById('settingsConnectBtn');
  if (btn) { btn.textContent = 'Testing...'; btn.disabled = true; }
  
  const newKey = document.getElementById('settingsApiKey').value.trim();
  const newBase = document.getElementById('settingsApiUrl').value.trim().replace(/\/$/, '');
  const remember = document.getElementById('settingsRememberKey')?.checked;

  try {
    const res = await fetch(`${newBase}/episodes?limit=1`, { headers: { Authorization: `Bearer ${newKey}` } });
    if (!res.ok) throw new Error('Invalid API key or URL');
    
    _cfg.apiKey = newKey;
    _cfg.apiBase = newBase;
    
    sessionStorage.setItem('ageval_key', newKey);
    sessionStorage.setItem('ageval_url', newBase);
    
    if (remember) {
      localStorage.setItem('ageval_key', newKey);
      localStorage.setItem('ageval_url', newBase);
    } else {
      localStorage.removeItem('ageval_key');
      localStorage.removeItem('ageval_url');
    }
    
    closeSettings();
    checkConnection();
    toast('Connected successfully', 'success');
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    if (btn) { btn.textContent = 'Test & Connect'; btn.disabled = false; }
  }
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

// ── Health ──────────────────────────────────────────────────────
let _trendChart = null;

async function loadHealth() {
  const statsRow = document.getElementById('healthStatsRow');
  if (!statsRow) return;
  statsRow.innerHTML = loading();
  
  try {
    const agentFilter = document.getElementById('healthAgentFilter')?.value || '';
    let path = `/episodes?limit=100`;
    if (agentFilter) path += `&agent_id=${encodeURIComponent(agentFilter)}`;
    const data = await apiGet(path);
    const eps = data.episodes || [];
    
    const now = new Date();
    const last7d = eps.filter(e => (now - new Date(e.created_at)) <= 7*24*60*60*1000);
    const prev7d = eps.filter(e => {
        const d = now - new Date(e.created_at);
        return d > 7*24*60*60*1000 && d <= 14*24*60*60*1000;
    });
    
    const avgScore7d = last7d.reduce((s, e) => s + (e.score || 0), 0) / (last7d.length || 1);
    const avgScorePrev = prev7d.reduce((s, e) => s + (e.score || 0), 0) / (prev7d.length || 1);
    const deltaScore = avgScore7d - avgScorePrev;
    
    const succ7d = last7d.filter(e => e.outcome === 'success').length / (last7d.length || 1);
    const succPrev = prev7d.filter(e => e.outcome === 'success').length / (prev7d.length || 1);
    const deltaSucc = succ7d - succPrev;
    
    statsRow.innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Avg Score (7d)</div>
        <div class="stat-value" style="font-size:28px">${avgScore7d.toFixed(2)}
          <span style="font-size:14px;color:${deltaScore >= 0 ? 'var(--success)' : 'var(--danger)'}">
            ${deltaScore >= 0 ? '▲' : '▼'} ${Math.abs(deltaScore).toFixed(2)}
          </span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Success Rate (7d)</div>
        <div class="stat-value" style="font-size:28px">${Math.round(succ7d*100)}%
          <span style="font-size:14px;color:${deltaSucc >= 0 ? 'var(--success)' : 'var(--danger)'}">
            ${deltaSucc >= 0 ? '▲' : '▼'} ${Math.round(Math.abs(deltaSucc)*100)}%
          </span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Episodes This Week</div>
        <div class="stat-value" style="font-size:28px">${last7d.length}</div>
      </div>
    `;
    
    try {
      const trendsData = await apiGet(`/trends` + (agentFilter ? `?agent_id=${encodeURIComponent(agentFilter)}` : ''));
      if (_trendChart) _trendChart.destroy();
      
      const ctx = document.getElementById('healthTrendChart').getContext('2d');
      _trendChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: trendsData.trends?.map(t => t.date) || [],
          datasets: [{
            label: 'Avg Score',
            data: trendsData.trends?.map(t => t.avg_score) || [],
            borderColor: '#f97316',
            backgroundColor: 'rgba(249,115,22,0.1)',
            fill: true,
            tension: 0.4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
              y: { min: 0, max: 1, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#a1a1aa' } },
              x: { grid: { display: false }, ticks: { color: '#a1a1aa' } }
          }
        }
      });
    } catch (e) {
      console.warn("Trends fetch failed", e);
    }
    
    const fails = eps.filter(e => e.outcome === 'failure').slice(0, 5);
    document.getElementById('healthRecentFailures').innerHTML = `
      <div class="card">
        <div class="card-header"><span class="card-title">Recent Failures</span></div>
        ${fails.map(e => `
          <div style="padding:12px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; cursor:pointer;" onclick="openDetail('${e.episode_id}')">
            <div>
               <div class="font-mono" style="color:var(--accent); font-size:13px;">${e.episode_id}</div>
               <div style="color:var(--text-muted); font-size:12px;">${escHtml(e.task || '')}</div>
            </div>
            <span class="badge badge-danger">${e.outcome}</span>
          </div>
        `).join('')}
        ${fails.length === 0 ? '<div style="padding:20px; color:var(--text-muted)">No recent failures.</div>' : ''}
      </div>
    `;
  } catch (err) {
    statsRow.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
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

    filterEpisodesClientSide();
  } catch (err) {
    tableEl.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
    if (err.message.includes('API key')) openSettings();
  }
}

function filterEpisodesClientSide() {
  const outcome = document.getElementById('outcomeFilter')?.value || '';
  const scoreF  = document.getElementById('scoreFilter')?.value || '';
  const dateF   = document.getElementById('dateFilter')?.value || '';
  const taskQ   = (document.getElementById('taskSearch')?.value || '').toLowerCase();

  let filtered = _episodes;
  if (outcome) filtered = filtered.filter(e => e.outcome === outcome);
  if (scoreF) {
    filtered = filtered.filter(e => {
      const s = e.score; 
      if (scoreF === 'unscored') return s == null;
      if (s == null) return false;
      if (scoreF === 'high') return s >= 0.8;
      if (scoreF === 'medium') return s >= 0.5 && s < 0.8;
      if (scoreF === 'low') return s < 0.5;
      return true;
    });
  }
  if (dateF) {
    const now = new Date();
    filtered = filtered.filter(e => {
      if (!e.created_at) return true;
      const d = new Date(e.created_at);
      const diffMs = now - d;
      const h = diffMs / (1000 * 60 * 60);
      if (dateF === '24h') return h <= 24;
      if (dateF === '7d') return h <= 24 * 7;
      if (dateF === '30d') return h <= 24 * 30;
      return true;
    });
  }
  if (taskQ) {
    filtered = filtered.filter(e => (e.task || '').toLowerCase().includes(taskQ));
  }

  renderStats(filtered);
  renderEpisodesTable(filtered);
}

function _refreshAgentFilter() {
  const agents = [..._agentIds].sort();
  const html = '<option value="">All agents</option>' + agents.map(a => `<option value="${escHtml(a)}">${escHtml(a)}</option>`).join('');
  const sel1 = document.getElementById('agentFilter');
  if (sel1) {
    const curr = sel1.value;
    sel1.innerHTML = html;
    sel1.value = curr;
  }
  const sel2 = document.getElementById('clusterAgentFilter');
  if (sel2) {
    const curr2 = sel2.value;
    sel2.innerHTML = html;
    sel2.value = curr2;
  }
  const sel3 = document.getElementById('healthAgentFilter');
  if (sel3) {
    const curr3 = sel3.value;
    sel3.innerHTML = html;
    sel3.value = curr3;
  }
  const dl = document.getElementById('compareEpList');
  if (dl && _episodes.length) {
      dl.innerHTML = _episodes.map(e => `<option value="${escHtml(e.episode_id)}">${escHtml(e.task || '')}</option>`).join('');
  }
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
          <th>Score</th>
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
          <tr class="ep-row" onclick="openDetail('${escHtml(e.episode_id)}')">
            <td>
              <span class="score-pill" style="color:${e.score != null ? scoreColor(e.score) : 'var(--text-muted)'}; font-weight:600">
                ${e.score != null ? `● ${Math.round(e.score * 100) / 100}` : '–'}
              </span>
            </td>
            <td class="font-mono" style="color:var(--accent)">${escHtml(e.episode_id)}</td>
            <td>${escHtml(e.agent_id || '—')}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(e.task || '')}">${escHtml(e.task || '—')}</td>
            <td><span class="badge badge-${outcomeClass(e.outcome)}">${e.outcome || 'pending'}</span></td>
            <td>${e.total_steps ?? '—'}</td>
            <td>${fmtLatency(e.total_latency_ms)}</td>
            <td style="position:relative;">
              ${fmtDate(e.created_at)}
              <div class="row-actions">
                 <button class="btn-ghost btn-sm" onclick="event.stopPropagation(); setCompareA('${escHtml(e.episode_id)}')">⇄ Compare</button>
                 <button class="btn-ghost btn-sm" onclick="event.stopPropagation(); setRecallTask('${escHtml((e.task||'').replace(/'/g, "\\'"))}')">◎ Find Similar</button>
              </div>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// ── Episode detail ──────────────────────────────────────────────
let _detailEpisodeId = null;
let _detailPollTimer = null;

const METRIC_DESC = {
  'success_rate': 'How often tool calls worked',
  'recovery_rate': 'How often the agent recovered from errors',
  'reasoning_coverage': 'How often the agent explained its decisions',
  'efficiency_score': 'Penalizes repeated identical tool calls',
  'task_completion': 'Did the agent accomplish the user request?',
  'reasoning_quality': 'Is the logic sound and easy to follow?',
  'error_handling': 'Did it handle failures gracefully?',
  'output_quality': 'Is the final answer well-formatted and accurate?'
};

async function openDetail(episodeId) {
  _detailEpisodeId = episodeId;
  if (_detailPollTimer) clearTimeout(_detailPollTimer);
  navigate('detail');

  const content = document.getElementById('detailContent');
  content.innerHTML = loading('Loading episode…');
  await fetchDetail(episodeId);
}

async function fetchDetail(episodeId, isPolling = false) {
  const content = document.getElementById('detailContent');
  const hId = document.getElementById('detailHeaderId');
  if (hId) hId.textContent = episodeId;
  const cBtn = document.getElementById('btnCopyEpId');
  if (cBtn) cBtn.onclick = () => { navigator.clipboard.writeText(episodeId); toast('ID copied'); };

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

    if (!scores.length && job && job.status !== 'done' && job.status !== 'failed') {
      _detailPollTimer = setTimeout(() => fetchDetail(episodeId, true), 5000);
    }
  } catch (err) {
    if (!isPolling) content.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
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
              <div class="breakdown-item" style="margin-bottom:8px;">
                <div style="flex:1">
                  <span class="breakdown-label">${k.replace(/_/g,' ')}</span>
                  ${METRIC_DESC[k] ? `<span style="font-size:11px;color:var(--text-muted);display:block;margin-top:2px;">${METRIC_DESC[k]}</span>` : ''}
                </div>
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
              <div class="breakdown-item" style="margin-bottom:8px;">
                <div style="flex:1">
                  <span class="breakdown-label">${k.replace(/_/g,' ')}</span>
                  ${METRIC_DESC[k] ? `<span style="font-size:11px;color:var(--text-muted);display:block;margin-top:2px;">${METRIC_DESC[k]}</span>` : ''}
                </div>
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

function navigateDetail(dir) {
  if (!_episodes.length || !_detailEpisodeId) return;
  const idx = _episodes.findIndex(e => e.episode_id === _detailEpisodeId);
  if (idx < 0) return;
  const nextIdx = idx + dir;
  if (nextIdx >= 0 && nextIdx < _episodes.length) {
    openDetail(_episodes[nextIdx].episode_id);
  }
}

// ── Compare ─────────────────────────────────────────────────────
function setCompareA(id) {
  document.getElementById('compareEpA').value = id;
  navigate('compare');
}

function swapCompare() {
  const a = document.getElementById('compareEpA');
  const b = document.getElementById('compareEpB');
  const tmp = a.value;
  a.value = b.value;
  b.value = tmp;
}

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
  
  let divergeIdx = -1;
  const maxLen = Math.max(steps_a?.length||0, steps_b?.length||0);
  for (let i=0; i<maxLen; i++) {
    const sa = steps_a?.[i];
    const sb = steps_b?.[i];
    if (!sa || !sb || sa.tool_name !== sb.tool_name || sa.success !== sb.success) {
      divergeIdx = i;
      break;
    }
  }

  document.getElementById('compareResult').innerHTML = `
    <div class="card" style="margin-bottom:24px;">
      <div style="display:flex;">
         <div style="flex:1; padding:16px; border-right:1px solid var(--border);">
            <div class="detail-meta-label">Episode A Score</div>
            <div style="font-size:24px; font-family:var(--font-heading); color:${scoreColor(episode_a?.score)}">${episode_a?.score != null ? Math.round(episode_a.score*100)+'%' : 'N/A'}</div>
         </div>
         <div style="flex:1; padding:16px;">
            <div class="detail-meta-label">Episode B Score</div>
            <div style="font-size:24px; font-family:var(--font-heading); color:${scoreColor(episode_b?.score)}">${episode_b?.score != null ? Math.round(episode_b.score*100)+'%' : 'N/A'}</div>
         </div>
      </div>
    </div>
    <div class="compare-grid">
      ${renderEpisodePanel('A', episode_a, steps_a, divergeIdx)}
      ${renderEpisodePanel('B', episode_b, steps_b, divergeIdx)}
    </div>
  `;
}

function renderEpisodePanel(label, ep, steps, divergeIdx) {
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
          ${i === divergeIdx ? `<div class="diverge-marker">◄ DIVERGES HERE ━━━━━━━━</div>` : ''}
          <div class="step-item" style="cursor:pointer" onclick="toggleStep('comp_${label}_${i}')" id="step-comp_${label}_${i}">
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
              ${s.reasoning ? `<div class="step-reasoning">${escHtml(s.reasoning)}</div>` : ''}
              ${s.tool_output != null ? `<div class="step-reasoning" id="step-output-comp_${label}_${i}" style="display:none">${jsonPreview(s.tool_output)}</div>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

// ── Recall ──────────────────────────────────────────────────────
function setRecallTask(task) {
  document.getElementById('recallQuery').value = task;
  navigate('recall');
  runRecall();
}

function setCompareB(id) {
  document.getElementById('compareEpB').value = id;
  if (_detailEpisodeId) document.getElementById('compareEpA').value = _detailEpisodeId;
  navigate('compare');
}

async function runRecall() {
  const query   = document.getElementById('recallQuery').value.trim();
  const outcome = document.getElementById('recallOutcome').value;
  const agent   = document.getElementById('recallAgent')?.value;
  const minS    = document.getElementById('recallMinScore')?.value;
  const dateF   = document.getElementById('recallDate')?.value;
  const k       = document.getElementById('recallK').value;
  const result  = document.getElementById('recallResult');

  if (!query) { toast('Enter a task description to search', 'error'); return; }

  result.innerHTML = loading('Searching episode memory…');

  try {
    let path = `/recall?task=${encodeURIComponent(query)}&k=${k}`;
    if (outcome) path += `&outcome=${encodeURIComponent(outcome)}`;
    if (agent) path += `&agent_id=${encodeURIComponent(agent)}`;

    const data = await apiGet(path);
    let eps  = data.episodes || [];
    
    // Client side filtering for score and date
    if (minS) {
      eps = eps.filter(e => e.score >= parseFloat(minS));
    }
    if (dateF) {
      const now = new Date();
      eps = eps.filter(e => {
        if (!e.created_at) return true;
        const h = (now - new Date(e.created_at)) / (1000 * 60 * 60);
        if (dateF === '7d') return h <= 24 * 7;
        if (dateF === '30d') return h <= 24 * 30;
        return true;
      });
    }

    if (!eps.length) {
      if (_episodes.length === 0) {
        result.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><p>No episodes yet. Run your agent with the AGeval SDK to start building memory.</p></div>`;
      } else if (!data.embeddings_exist && !eps.length) {
        result.innerHTML = `<div class="empty-state"><div class="empty-icon">⚙️</div><p>Embeddings haven't been generated yet. Make sure OPENAI_API_KEY is set on your server and the merger worker is running.</p></div>`;
      } else {
        result.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>No similar episodes found matching criteria.</p></div>`;
      }
      return;
    }

    result.innerHTML = eps.map(e => `
      <div class="recall-card">
        <div class="recall-task" onclick="openDetail('${escHtml(e.episode_id)}')">${escHtml(e.task || e.episode_id)}</div>
        <div class="recall-meta">
          <span class="badge badge-${outcomeClass(e.outcome)}">${e.outcome || '?'}</span>
          <span>${escHtml(e.agent_id || '—')}</span>
          <span>${e.total_steps ?? '?'} steps</span>
          ${e.similarity != null ? `<span class="similarity-badge">⬡ ${Math.round(e.similarity * 100)}% match</span>` : ''}
          <span style="color:${scoreColor(e.score)}; font-weight:bold;">${e.score != null ? '● '+Math.round(e.score*100)/100 : ''}</span>
          <div style="flex:1"></div>
          <button class="btn-ghost btn-sm" onclick="event.stopPropagation(); setCompareB('${escHtml(e.episode_id)}')">Compare→B</button>
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

// ── Clusters ────────────────────────────────────────────────────
async function loadClusters() {
  const resultEl = document.getElementById('clustersResult');
  resultEl.innerHTML = loading('Loading clusters…');
  try {
    const agentFilter = document.getElementById('clusterAgentFilter')?.value || '';
    let path = `/clusters`;
    if (agentFilter) path += `?agent_id=${encodeURIComponent(agentFilter)}`;
    
    const data = await apiGet(path);
    const clusters = data.clusters || [];
    
    if (!clusters.length) {
      resultEl.innerHTML = `<div class="empty-state"><div class="empty-icon">📊</div><p>No clusters found. Run more tasks and wait for the background worker to group them.</p></div>`;
      return;
    }
    
    resultEl.innerHTML = `<div class="clusters-grid" style="display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">` + 
      clusters.map(c => `
        <div class="card">
          <div class="card-header"><span class="card-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${escHtml(c.label)}">${escHtml(c.label)}</span></div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Episodes</span>
            <span class="detail-meta-value">${c.episode_count}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Avg Score</span>
            <span class="detail-meta-value" style="color:${scoreColor(c.avg_score)};font-weight:600">
              ${c.avg_score != null ? Math.round(c.avg_score*100)+'%' : 'N/A'}
              ${c.drift != null ? `<span style="font-size:12px;margin-left:8px;color:${c.drift >= 0 ? 'var(--success)' : 'var(--danger)'}">${c.drift >= 0 ? '▲' : '▼'}${Math.abs(Math.round(c.drift*100))}%</span>` : ''}
            </span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Top Failing Tool</span>
            <span class="detail-meta-value">${c.top_failing_tool ? escHtml(c.top_failing_tool) : '<span style="color:var(--text-muted)">None</span>'}</span>
          </div>
          <div class="detail-meta-item">
            <span class="detail-meta-label">Agent</span>
            <span class="detail-meta-value">${escHtml(c.agent_id)}</span>
          </div>
        </div>
      `).join('') + `</div>`;
  } catch (err) {
    resultEl.innerHTML = `<div class="error-msg">⚠ ${escHtml(err.message)}</div>`;
  }
}

// ── Boot ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkConnection();
  if (!_cfg.apiKey) {
    setTimeout(openSettings, 300);
  }
  navigate('health');
});
