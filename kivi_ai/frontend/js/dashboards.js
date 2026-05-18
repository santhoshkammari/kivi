// ===== GIT DASHBOARD =====
let _gitCurrentPath = '';
let _gitRecentPaths = JSON.parse(localStorage.getItem('git_recent_paths') || '[]');
let _gitSearchTimer = null;

function showGitDashboard() {
  document.getElementById('welcomeScreen').classList.add('hidden');
  document.getElementById('messagesArea').classList.remove('active');
  document.getElementById('messagesArea').style.display = 'none';
  document.getElementById('chatInputArea').style.display = 'none';
  document.getElementById('chatHeader').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'none';
  document.getElementById('chatsDashboard').style.display = 'none';
  document.getElementById('agentsDashboard').style.display = 'none';
  document.getElementById('gitDashboard').style.display = 'flex';
  renderGitRecents();
}

function hideGitDashboard() {
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = '';
}

// ===== TOKEN BURNING DASHBOARD =====
let _tokenStats = null;
let _tokenPeriod = 'today';

function showTokenDashboard() {
  document.getElementById('welcomeScreen').classList.add('hidden');
  document.getElementById('messagesArea').classList.remove('active');
  document.getElementById('messagesArea').style.display = 'none';
  document.getElementById('chatInputArea').style.display = 'none';
  document.getElementById('chatHeader').style.display = 'none';
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('chatsDashboard').style.display = 'none';
  document.getElementById('agentsDashboard').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'flex';
  loadTokenStats();
}

function hideTokenDashboard() {
  document.getElementById('tokenDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = '';
}

function setTokenPeriod(p) {
  _tokenPeriod = p;
  document.querySelectorAll('.tkn-period').forEach(b => b.classList.toggle('active', b.dataset.period === p));
  if (_tokenStats) renderTokenDashboard(_tokenStats);
}

async function loadTokenStats() {
  try {
    const resp = await fetch('/api/usage');
    _tokenStats = await resp.json();
    renderTokenDashboard(_tokenStats);
  } catch(e) { console.error('Token stats error:', e); }
}

async function refreshTokenStats() {
  const btn = document.getElementById('tokenRefreshBtn');
  btn.textContent = '⏳ Refreshing...';
  btn.disabled = true;
  try {
    await fetch('/api/usage');
    await loadTokenStats();
  } finally {
    btn.textContent = '↻ Refresh';
    btn.disabled = false;
  }
}

function renderTokenDashboard(stats) {
  const data = stats[_tokenPeriod] || { input: 0, output: 0, cost: 0, by_mode: {}, daily: [], hourly: [], insights: {}, by_chat: [] };
  const total = data.input + data.output;
  const insights = data.insights || {};

  // Summary cards
  const cards = document.getElementById('tokenSummaryCards');
  cards.innerHTML = [
    { label: 'Total Tokens', value: formatTokenCount(total), sub: 'input + output', icon: '🔢' },
    { label: 'Input', value: formatTokenCount(data.input), sub: 'prompt tokens', icon: '📥' },
    { label: 'Output', value: formatTokenCount(data.output), sub: 'completion tokens', icon: '📤' },
    { label: 'Cost', value: '$' + data.cost.toFixed(4), sub: 'estimated USD', icon: '💰' },
  ].map(c => '<div class="tkn-card"><div class="label">' + c.icon + ' ' + c.label + '</div><div class="value">' + c.value + '</div><div class="sub">' + c.sub + '</div></div>').join('');

  // Insights row
  const insEl = document.getElementById('tokenInsights');
  const peakLabel = insights.peak_hour != null ? (insights.peak_hour % 12 || 12) + (insights.peak_hour < 12 ? 'AM' : 'PM') : '—';
  insEl.innerHTML = [
    { label: 'Messages', value: String(insights.total_msgs || 0), sub: 'total exchanges', icon: '💬' },
    { label: 'Avg/Message', value: formatTokenCount(insights.avg_per_msg || 0), sub: 'tokens per msg', icon: '📊' },
    { label: 'Peak Hour', value: peakLabel, sub: 'busiest hour', icon: '⏰' },
    { label: 'Top Model', value: (insights.top_model || '—').split('/').pop().slice(0, 14), sub: 'most used', icon: '🤖' },
  ].map(c => '<div class="tkn-card"><div class="label">' + c.icon + ' ' + c.label + '</div><div class="value" style="font-size:20px;">' + c.value + '</div><div class="sub">' + c.sub + '</div></div>').join('');

  // Plotly chart
  const chartDiv = document.getElementById('tokenPlotlyChart');
  const isToday = _tokenPeriod === 'today';
  const hourly = data.hourly || [];
  const daily = data.daily || [];
  const plotlyLayout = {
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { color: '#e0e0e0', size: 12 },
    margin: { l: 50, r: 20, t: 40, b: 40 },
    barmode: 'stack',
    legend: { orientation: 'h', y: -0.15, font: { size: 11 } },
    xaxis: { gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 10 } },
    yaxis: { gridcolor: 'rgba(255,255,255,0.06)', title: 'Tokens', tickfont: { size: 10 } },
  };
  const plotlyConfig = { responsive: true, displayModeBar: false };

  if (isToday && hourly.length) {
    // Stacked bar by mode per hour
    const allModes = new Set();
    hourly.forEach(h => Object.keys(h.modes || {}).forEach(m => allModes.add(m)));
    const modeList = [...allModes];
    const xLabels = hourly.map(h => {
      const hr = h.hour % 12 || 12;
      return hr + (h.hour < 12 ? 'AM' : 'PM');
    });
    const traces = modeList.map(m => ({
      x: xLabels,
      y: hourly.map(h => (h.modes[m] || {}).tokens || 0),
      name: MODE_LABELS[m] || m,
      type: 'bar',
      marker: { color: MODE_COLORS[m] || '#888', line: { width: 0 } },
      hovertemplate: '%{y:,.0f} tokens<extra>' + (MODE_LABELS[m] || m) + '</extra>',
    }));
    if (!traces.length) {
      traces.push({ x: xLabels, y: hourly.map(() => 0), type: 'bar', marker: { color: '#444' }, showlegend: false });
    }
    plotlyLayout.title = { text: 'Hourly Usage — ' + new Date().toLocaleDateString('en-US', {weekday:'long', month:'short', day:'numeric'}), font: { size: 14 } };
    Plotly.newPlot(chartDiv, traces, plotlyLayout, plotlyConfig);
  } else if (daily.length) {
    // Grouped bars: input vs output per day, colored by mode if available
    const allModes = new Set();
    Object.keys(data.by_mode || {}).forEach(m => allModes.add(m));
    const modeList = [...allModes];
    const xLabels = daily.map(d => d.date || '');

    if (modeList.length > 1) {
      // If multiple modes, show mode breakdown per day from hourly data
      const traces = [
        { x: xLabels, y: daily.map(d => d.input), name: 'Input', type: 'bar',
          marker: { color: '#7aaeE0', line: { width: 0 } },
          hovertemplate: '%{y:,.0f} tokens<extra>Input</extra>' },
        { x: xLabels, y: daily.map(d => d.output), name: 'Output', type: 'bar',
          marker: { color: '#d9774f', line: { width: 0 } },
          hovertemplate: '%{y:,.0f} tokens<extra>Output</extra>' },
      ];
      plotlyLayout.barmode = 'group';
      plotlyLayout.title = { text: 'Daily Usage', font: { size: 14 } };
      Plotly.newPlot(chartDiv, traces, plotlyLayout, plotlyConfig);
    } else {
      const traces = [
        { x: xLabels, y: daily.map(d => d.input), name: 'Input', type: 'bar',
          marker: { color: '#7aaeE0' }, hovertemplate: '%{y:,.0f}<extra>Input</extra>' },
        { x: xLabels, y: daily.map(d => d.output), name: 'Output', type: 'bar',
          marker: { color: '#d9774f' }, hovertemplate: '%{y:,.0f}<extra>Output</extra>' },
      ];
      plotlyLayout.barmode = 'group';
      plotlyLayout.title = { text: 'Daily Usage', font: { size: 14 } };
      Plotly.newPlot(chartDiv, traces, plotlyLayout, plotlyConfig);
    }
  } else {
    Plotly.newPlot(chartDiv, [], { ...plotlyLayout,
      title: { text: isToday ? 'Hourly Usage' : 'Daily Usage', font: { size: 14 } },
      annotations: [{ text: 'No data for this period', showarrow: false, font: { size: 14, color: '#888' } }]
    }, plotlyConfig);
  }

  // Mode breakdown with horizontal bars (like LLM benchmark charts)
  const modeEl = document.getElementById('tokenModeBreakdown');
  const modes = Object.entries(data.by_mode || {});
  if (!modes.length) {
    modeEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No usage data yet</div>';
  } else {
    // Sort by total tokens descending
    modes.sort((a, b) => (b[1].input + b[1].output) - (a[1].input + a[1].output));
    const modeNames = modes.map(([m]) => MODE_LABELS[m] || m);
    const inputVals = modes.map(([,v]) => v.input);
    const outputVals = modes.map(([,v]) => v.output);
    const modeColors = modes.map(([m]) => MODE_COLORS[m] || '#888');

    const modeTraces = [
      { y: modeNames, x: inputVals, name: 'Input', type: 'bar', orientation: 'h',
        marker: { color: modeColors.map(c => c + 'cc') },
        hovertemplate: '%{x:,.0f} tokens<extra>Input</extra>', text: inputVals.map(v => formatTokenCount(v)), textposition: 'inside', textfont: { size: 11, color: '#fff' } },
      { y: modeNames, x: outputVals, name: 'Output', type: 'bar', orientation: 'h',
        marker: { color: modeColors },
        hovertemplate: '%{x:,.0f} tokens<extra>Output</extra>', text: outputVals.map(v => formatTokenCount(v)), textposition: 'inside', textfont: { size: 11, color: '#fff' } },
    ];
    const modePlotDiv = document.createElement('div');
    modePlotDiv.style.cssText = 'width:100%;height:' + Math.max(modes.length * 50, 120) + 'px;';
    modeEl.innerHTML = '';
    modeEl.appendChild(modePlotDiv);

    // Add cost summary below
    const costSummary = document.createElement('div');
    costSummary.style.cssText = 'display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;';
    costSummary.innerHTML = modes.map(([m, v]) => {
      const c = MODE_COLORS[m] || '#888';
      const l = MODE_LABELS[m] || m;
      return '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary);"><span style="width:10px;height:10px;border-radius:3px;background:' + c + ';display:inline-block;"></span>' + l + ': ' + formatTokenCount(v.input + v.output) + ' · $' + v.cost.toFixed(4) + ' · ' + v.count + ' msgs</div>';
    }).join('');
    modeEl.appendChild(costSummary);

    Plotly.newPlot(modePlotDiv, modeTraces, {
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { color: '#e0e0e0', size: 12 },
      margin: { l: 100, r: 20, t: 10, b: 30 },
      barmode: 'stack',
      xaxis: { gridcolor: 'rgba(255,255,255,0.06)', title: 'Tokens' },
      yaxis: { automargin: true },
      showlegend: false,
    }, plotlyConfig);
  }

  // Per-chat breakdown
  const chatBrkEl = document.getElementById('tokenChatBreakdown');
  const byChat = data.by_chat || [];
  if (!byChat.length) {
    chatBrkEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No chat data yet</div>';
  } else {
    chatBrkEl.innerHTML = byChat.map(ch => {
      const total = ch.input + ch.output;
      const modeColor = MODE_COLORS[ch.mode] || '#888';
      const modeLabel = MODE_LABELS[ch.mode] || ch.mode;
      const timeAgo = _timeAgo(ch.started);
      return '<div style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:8px;background:var(--bg-surface-alt);margin-bottom:6px;cursor:pointer;" onclick="switchToChat(\'' + ch.chat_id + '\');hideTokenDashboard();">' +
        '<div style="width:8px;height:8px;border-radius:50%;background:' + modeColor + ';flex-shrink:0;"></div>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(ch.title) + '</div>' +
          '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">' + modeLabel + ' · ' + (ch.model || '').split('/').pop().slice(0,20) + ' · ' + timeAgo + '</div>' +
        '</div>' +
        '<div style="text-align:right;flex-shrink:0;">' +
          '<div style="font-size:13px;font-weight:500;">' + formatTokenCount(total) + '</div>' +
          '<div style="font-size:11px;color:var(--text-muted);">$' + ch.cost.toFixed(4) + '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }
}


function _timeAgo(dateStr) {
  if (!dateStr) return '';
  let ts;
  if (typeof dateStr === 'number') {
    ts = dateStr > 1e12 ? dateStr : dateStr * 1000;
  } else {
    ts = new Date(dateStr + (dateStr.includes('T') ? '' : 'T00:00:00')).getTime();
  }
  const diff = (Date.now() - ts) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function formatTokenCount(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

// ── Chats Dashboard ──
function showChatsDashboard() {
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'none';
  document.getElementById('chatsDashboard').style.display = 'none';
  document.getElementById('agentsDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = '';
  if (currentSessionId) {
    switchToChat(currentSessionId);
  } else {
    newChat();
  }
  const list = document.getElementById('chatList');
  if (list) list.scrollTo({ top: 0, behavior: 'smooth' });
}

function hideChatsDashboard() {}

async function renderChatsDashboard() {
  renderChatList();
}

function filterChatsDashboard() {
  renderChatList();
}

function renderGitRecents() {
  const el = document.getElementById('gitRecentRepos');
  if (!_gitRecentPaths.length) {
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">Search for a git repo above to get started.</div>';
    return;
  }
  el.innerHTML = _gitRecentPaths.slice(0, 8).map(p => {
    const name = p.split('/').pop();
    return '<div class="git-repo-card" onclick="gitLoadRepo(\'' + esc(p) + '\')">' +
      '<div style="font-weight:500;">' + esc(name) + '</div>' +
      '<div class="path">' + esc(p) + '</div></div>';
  }).join('');
}

function gitSearchDirs(q) {
  clearTimeout(_gitSearchTimer);
  const el = document.getElementById('gitSearchResults');
  if (!q || q.length < 2) { el.style.display = 'none'; return; }
  _gitSearchTimer = setTimeout(async () => {
    try {
      const resp = await fetch('/api/files?q=' + encodeURIComponent(q) + '&limit=30');
      const files = await resp.json();
      const dirs = [...new Set((files || []).map(f => (f || '').split('/').slice(0, -1).join('/')).filter(Boolean))].slice(0, 15);
      if (!dirs.length) { el.style.display = 'none'; return; }
      el.innerHTML = dirs.map(d => `<div class="git-search-item" onclick="gitSelectRepo('${esc(d)}')">${esc(d)}</div>`).join('');
      el.style.display = 'block';
    } catch(e) { el.style.display = 'none'; }
  }, 300);
}

function gitSelectRepo(path) {
  document.getElementById('gitSearchInput').value = path;
  document.getElementById('gitSearchResults').style.display = 'none';
  gitLoadRepo(path);
}

async function gitLoadRepo(path) {
  _gitCurrentPath = path;
  // Add to recents
  _gitRecentPaths = [path, ..._gitRecentPaths.filter(p => p !== path)].slice(0, 20);
  localStorage.setItem('git_recent_paths', JSON.stringify(_gitRecentPaths));
  renderGitRecents();

  document.getElementById('gitRepoInfo').style.display = 'block';
  document.getElementById('gitRepoPath').textContent = path;
  document.getElementById('gitDiffView').innerHTML = '<div style="color:var(--text-muted);padding:20px;">Loading diff...</div>';

  try {
    const resp = await fetch('/api/git/diff?path=' + encodeURIComponent(path));
    const data = await resp.json();
    if (data.error) { document.getElementById('gitDiffView').innerHTML = '<div style="color:var(--red);">' + esc(data.error) + '</div>'; return; }

    document.getElementById('gitBranch').textContent = '⎇ ' + data.branch;
    const statusLines = data.status ? data.status.split('\n').filter(l => l.trim()) : [];
    document.getElementById('gitChangeCount').textContent = statusLines.length ? statusLines.length + ' changed file(s)' : 'Clean working tree';
    document.getElementById('gitCommitBtn').style.display = data.has_changes ? '' : 'none';

    // Render diff
    const allDiff = (data.staged || '') + '\n' + (data.unstaged || '') + '\n' + (data.untracked || '');
    document.getElementById('gitDiffView').innerHTML = renderGitDiff(allDiff, data.status);

    // Render commits
    renderGitCommitLog(data.commits);
  } catch(e) {
    document.getElementById('gitDiffView').innerHTML = '<div style="color:var(--red);">Error loading diff: ' + esc(e.message) + '</div>';
  }
}

function renderGitDiff(diffText, statusText) {
  if (!diffText.trim() && !statusText?.trim()) return '<div style="color:var(--text-muted);padding:20px;">No changes detected.</div>';

  // Parse unified diff into files
  const files = [];
  const chunks = diffText.split(/^diff --git /m).filter(c => c.trim());

  for (const chunk of chunks) {
    const lines = chunk.split('\n');
    let fileName = '';
    // Try to get file name from +++ line
    for (const l of lines) {
      if (l.startsWith('+++ b/')) { fileName = l.slice(6); break; }
      if (l.startsWith('+++ ')) { fileName = l.slice(4); break; }
    }
    if (!fileName) {
      // Fallback: parse from first line "a/file b/file"
      const m = lines[0].match(/b\/(.+)/);
      if (m) fileName = m[1];
    }
    files.push({ name: fileName || 'unknown', lines: lines });
  }

  // Also parse untracked files (--- /dev/null format)
  if (!chunks.length && diffText.trim()) {
    const untrackedChunks = diffText.split(/\n(?=--- \/dev\/null)/).filter(c => c.trim());
    for (const chunk of untrackedChunks) {
      const lines = chunk.split('\n');
      let fileName = '';
      for (const l of lines) {
        if (l.startsWith('+++ b/')) { fileName = l.slice(6); break; }
      }
      files.push({ name: fileName || 'new file', lines: lines });
    }
  }

  if (!files.length) return '<div style="color:var(--text-muted);padding:20px;">No diff content to display.</div>';

  let html = '';
  for (const file of files) {
    const isNew = file.lines.some(l => l.startsWith('new file'));
    const isDel = file.lines.some(l => l.startsWith('deleted file'));
    const badgeClass = isNew ? 'badge-new' : isDel ? 'badge-del' : 'badge-mod';
    const badgeText = isNew ? 'NEW' : isDel ? 'DEL' : 'MOD';

    html += '<div class="diff-file">';
    html += '<div class="diff-file-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">';
    html += '<span class="badge ' + badgeClass + '">' + badgeText + '</span>';
    html += '<span>' + esc(file.name) + '</span>';

    // Count additions/deletions
    let adds = 0, dels = 0;
    for (const l of file.lines) {
      if (l.startsWith('+') && !l.startsWith('+++')) adds++;
      if (l.startsWith('-') && !l.startsWith('---')) dels++;
    }
    if (adds || dels) {
      html += '<span style="margin-left:auto;font-size:12px;">';
      if (adds) html += '<span style="color:var(--green);">+' + adds + '</span> ';
      if (dels) html += '<span style="color:var(--red);">-' + dels + '</span>';
      html += '</span>';
    }
    html += '</div>';

    html += '<div class="diff-lines">';
    let lineNoOld = 0, lineNoNew = 0;
    for (const l of file.lines) {
      if (l.startsWith('@@')) {
        const m = l.match(/@@ -(\d+)/);
        if (m) lineNoOld = parseInt(m[1]);
        const m2 = l.match(/\+(\d+)/);
        if (m2) lineNoNew = parseInt(m2[1]);
        html += '<div class="diff-line diff-line-hunk"><div class="diff-line-num"></div><div class="diff-line-num"></div><div class="diff-line-content">' + esc(l) + '</div></div>';
      } else if (l.startsWith('+') && !l.startsWith('+++')) {
        html += '<div class="diff-line diff-line-add"><div class="diff-line-num"></div><div class="diff-line-num">' + (lineNoNew++) + '</div><div class="diff-line-content">' + esc(l) + '</div></div>';
      } else if (l.startsWith('-') && !l.startsWith('---')) {
        html += '<div class="diff-line diff-line-del"><div class="diff-line-num">' + (lineNoOld++) + '</div><div class="diff-line-num"></div><div class="diff-line-content">' + esc(l) + '</div></div>';
      } else if (!l.startsWith('diff') && !l.startsWith('index') && !l.startsWith('---') && !l.startsWith('+++') && !l.startsWith('new file') && !l.startsWith('deleted file') && !l.startsWith('old mode') && !l.startsWith('new mode') && !l.startsWith('similarity') && !l.startsWith('rename') && !l.startsWith('Binary')) {
        html += '<div class="diff-line diff-line-ctx"><div class="diff-line-num">' + (lineNoOld++) + '</div><div class="diff-line-num">' + (lineNoNew++) + '</div><div class="diff-line-content">' + esc(l || ' ') + '</div></div>';
      }
    }
    html += '</div></div>';
  }
  return html;
}

function renderGitCommitLog(commits) {
  const el = document.getElementById('gitCommitLog');
  if (!commits || !commits.length) { el.innerHTML = ''; return; }
  let html = '<h3 style="font-size:14px;font-weight:600;margin-bottom:8px;color:var(--text-secondary);">Recent Commits</h3>';
  html += '<div style="border:1px solid var(--border-subtle);border-radius:10px;overflow:hidden;">';
  for (const c of commits) {
    html += '<div class="git-commit-item">';
    html += '<span class="git-commit-sha">' + esc(c.short) + '</span>';
    html += '<span class="git-commit-msg">' + esc(c.msg) + '</span>';
    html += '<span class="git-commit-meta">' + esc(c.author) + '</span>';
    html += '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
}

function gitRefresh() { if (_gitCurrentPath) gitLoadRepo(_gitCurrentPath); }

function gitCommitPrompt() {
  const area = document.getElementById('gitCommitArea');
  area.style.display = area.style.display === 'none' ? '' : 'none';
  if (area.style.display !== 'none') document.getElementById('gitCommitMsg').focus();
}

async function gitDoCommit() {
  const msg = document.getElementById('gitCommitMsg').value.trim();
  if (!msg) { showToast('Please enter a commit message'); return; }
  try {
    const resp = await fetch('/api/git/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: _gitCurrentPath, message: msg }),
    });
    const data = await resp.json();
    if (data.success) {
      showToast('Committed!');
      document.getElementById('gitCommitMsg').value = '';
      document.getElementById('gitCommitArea').style.display = 'none';
      gitRefresh();
    } else {
      showToast('Commit failed: ' + data.output);
    }
  } catch(e) { showToast('Commit error: ' + e.message); }
}

async function gitPush() {
  try {
    const resp = await fetch('/api/git/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: _gitCurrentPath }),
    });
    const data = await resp.json();
    showToast(data.success ? 'Pushed!' : 'Push failed: ' + data.output);
  } catch(e) { showToast('Push error: ' + e.message); }
}

// Close git search dropdown when clicking outside
document.addEventListener('click', (e) => {
  if (!e.target.closest('#gitSearchInput') && !e.target.closest('#gitSearchResults')) {
    document.getElementById('gitSearchResults').style.display = 'none';
  }
});


// ===== INIT =====
