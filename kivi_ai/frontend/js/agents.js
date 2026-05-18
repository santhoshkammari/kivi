// ===== AGENTS DASHBOARD =====

let _agentsData = [];
let _agentsPollInterval = null;

function showAgentsDashboard() {
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'none';
  document.getElementById('chatsDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = 'none';
  document.getElementById('welcomeScreen').classList.add('hidden');
  document.getElementById('chatInputArea').style.display = 'none';
  document.getElementById('chatHeader').style.display = 'none';
  document.getElementById('agentsDashboard').style.display = '';
  refreshAgents();
  // Poll while dashboard is visible
  _startAgentsPoll();
}

function hideAgentsDashboard() {
  document.getElementById('agentsDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = '';
  document.getElementById('chatInputArea').style.display = '';
  document.getElementById('chatHeader').style.display = '';
  _stopAgentsPoll();
}

function _startAgentsPoll() {
  _stopAgentsPoll();
  _agentsPollInterval = setInterval(refreshAgents, 3000);
}

function _stopAgentsPoll() {
  if (_agentsPollInterval) { clearInterval(_agentsPollInterval); _agentsPollInterval = null; }
}

async function refreshAgents() {
  try {
    const resp = await fetch('/api/agents');
    _agentsData = await resp.json();
  } catch(e) {
    _agentsData = [];
  }
  renderAgentsDashboard();
  updateAgentsBadge();
}

function updateAgentsBadge() {
  const badge = document.getElementById('agentsBadge');
  if (!badge) return;
  const running = _agentsData.filter(a => a.status === 'running').length;
  if (running > 0) {
    badge.textContent = running;
    badge.style.display = '';
  } else {
    badge.style.display = 'none';
  }
}

function renderAgentsDashboard() {
  const running = _agentsData.filter(a => a.status === 'running');
  const completed = _agentsData.filter(a => a.status !== 'running');

  const runningEl = document.getElementById('agentsRunningList');
  const completedEl = document.getElementById('agentsCompletedList');
  const runningSection = document.getElementById('agentsRunningSection');
  const completedSection = document.getElementById('agentsCompletedSection');

  if (!runningEl || !completedEl) return;

  runningSection.style.display = running.length ? '' : 'none';
  completedSection.style.display = completed.length ? '' : 'none';

  if (!running.length && !completed.length) {
    runningSection.style.display = '';
    runningEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:14px;">No active agents. Start a chat with tools to see agents here.</div>';
    return;
  }

  runningEl.innerHTML = running.map(a => _renderAgentCard(a)).join('');
  completedEl.innerHTML = completed.map(a => _renderAgentCard(a)).join('');
}

function _renderAgentCard(agent) {
  const modeColor = MODE_COLORS[agent.provider] || MODE_COLORS[agent.mode] || '#7aaeE0';
  const modeLabel = MODE_LABELS[agent.mode] || agent.provider;
  const elapsed = _formatElapsed(agent.elapsed);
  const isRunning = agent.status === 'running';

  const statusHtml = isRunning
    ? '<span style="display:inline-flex;align-items:center;gap:4px;color:var(--green);font-size:12px;font-weight:500;"><span class="agent-pulse"></span>Running</span>'
    : '<span style="color:var(--text-muted);font-size:12px;">✓ Done</span>';

  const toolsHtml = agent.tool_count > 0
    ? `<span style="font-size:11px;color:var(--text-muted);background:var(--bg-surface-alt);padding:2px 6px;border-radius:4px;">${agent.tool_count} tool${agent.tool_count > 1 ? 's' : ''}</span>`
    : '';

  return `<div onclick="hideAgentsDashboard();switchToChat('${agent.session_id}')" 
    style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:10px;border:1px solid var(--border-subtle);background:var(--bg-secondary);cursor:pointer;transition:background 0.15s;"
    onmouseenter="this.style.background='var(--bg-surface-alt)'" onmouseleave="this.style.background='var(--bg-secondary)'">
    <div style="width:8px;height:8px;border-radius:50%;background:${modeColor};flex-shrink:0;"></div>
    <div style="flex:1;min-width:0;">
      <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(agent.title || 'Untitled')}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:3px;">
        <span style="font-size:11px;color:${modeColor};font-weight:500;">${modeLabel}</span>
        ${toolsHtml}
      </div>
    </div>
    <div style="text-align:right;flex-shrink:0;">
      ${statusHtml}
      <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${elapsed}</div>
    </div>
  </div>`;
}

function _formatElapsed(seconds) {
  if (seconds < 60) return Math.round(seconds) + 's';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
  return Math.round(seconds / 3600) + 'h ' + Math.round((seconds % 3600) / 60) + 'm';
}

// Poll agents badge in background (even when not on dashboard)
setInterval(async () => {
  try {
    const resp = await fetch('/api/agents');
    _agentsData = await resp.json();
    updateAgentsBadge();
  } catch(e) {}
}, 5000);
