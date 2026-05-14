// ===== SESSION MANAGEMENT =====
function getSession(id) { return sessions.find(s => s.id === id); }

async function loadSessions() {
  // Load persisted mode map from localStorage (session_id → mode)
  let modeMap = {};
  try { modeMap = JSON.parse(localStorage.getItem('kivi_session_modes') || '{}'); } catch(e) {}
  try {
    const resp = await fetch('/api/sessions');
    const serverSessions = await resp.json();
    // Merge locally-stored mode into server sessions
    sessions = serverSessions.map(s => ({ ...s, mode: modeMap[s.id] || s.mode || 'kivi' }));
  } catch(e) {
    console.warn('Failed to load sessions:', e);
    sessions = [];
  }
  renderChatList();
}

function _saveSessionMode(id, mode) {
  try {
    const m = JSON.parse(localStorage.getItem('kivi_session_modes') || '{}');
    m[id] = mode;
    // Keep only last 200 sessions to avoid unbounded growth
    const keys = Object.keys(m);
    if (keys.length > 200) keys.slice(0, keys.length - 200).forEach(k => delete m[k]);
    localStorage.setItem('kivi_session_modes', JSON.stringify(m));
  } catch(e) {}
}

function newChat() {
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'none';
  document.getElementById('messagesArea').style.display = '';
  currentSessionId = null;
  currentMessages = [];
  isStreaming = false;
  abortController = null;
  stopRequested = false;
  document.getElementById('welcomeScreen').classList.remove('hidden');
  document.getElementById('messagesArea').classList.remove('active');
  document.getElementById('messagesArea').innerHTML = '';
  document.getElementById('chatInputArea').style.display = 'none';
  document.getElementById('chatHeader').style.display = 'none';
  document.getElementById('welcomeInput').value = '';
  document.getElementById('welcomeInput').focus();
  uploadedFiles.welcome = []; uploadedFiles.chat = [];
  renderFileChips('welcome'); renderFileChips('chat');
  renderChatList();
  updateSendButton();
}

async function createSession(firstMessage) {
  const provider = MODE_TO_PROVIDER[currentMode] || 'vllm';
  const title = firstMessage.substring(0, 50) + (firstMessage.length > 50 ? '...' : '');
  try {
    const resp = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model: currentModelId, title }),
    });
    const data = await resp.json();
    const session = { id: data.id, title, provider, model: currentModelId, mode: currentMode, created_at: Date.now(), updated_at: Date.now() };
    sessions.unshift(session);
    currentSessionId = data.id;
    _saveSessionMode(data.id, currentMode);
    currentMessages = [];
    renderChatList();
    return data.id;
  } catch(e) {
    console.error('createSession error:', e);
    // Fallback: use temp ID, server will create on first stream
    const id = 'temp-' + Date.now();
    sessions.unshift({ id, title, mode: currentMode, created_at: Date.now() });
    currentSessionId = id;
    currentMessages = [];
    renderChatList();
    return null; // null means let server create
  }
}

async function switchToChat(id) {
  document.getElementById('gitDashboard').style.display = 'none';
  document.getElementById('tokenDashboard').style.display = 'none';
  const chatsDash = document.getElementById('chatsDashboard');
  if (chatsDash) chatsDash.style.display = 'none';
  document.getElementById('messagesArea').style.display = '';

  currentSessionId = id;
  isStreaming = false;
  abortController = null;
  stopRequested = false;

  // Load messages from server
  try {
    const resp = await fetch('/api/sessions/' + encodeURIComponent(id) + '/messages');
    currentMessages = await resp.json();
  } catch(e) {
    console.warn('Failed to load messages:', e);
    currentMessages = [];
  }

  // Update UI
  document.getElementById('welcomeScreen').classList.add('hidden');
  document.getElementById('messagesArea').classList.add('active');
  document.getElementById('chatInputArea').style.display = '';
  document.getElementById('chatHeader').style.display = '';

  const session = getSession(id);
  const title = session?.title || 'Chat';
  document.getElementById('chatTitleText').textContent = title;

  // Set mode/model from session — prefer session.mode, fall back to provider
  if (session) {
    const providerToMode = { copilot: 'copilot', 'qwen-copilot': 'qwen-copilot', claude: 'claude', 'qwen-claude': 'qwen-claude' };
    const mode = session.mode || providerToMode[session.provider] || 'kivi';
    if (session.model) currentModelId = session.model;
    if (mode !== currentMode) {
      await setMode(mode);
    } else {
      await updateModelSelectors();
    }
    document.querySelectorAll('.model-selector').forEach(sel => { sel.value = currentModelId; });
  }

  // Render messages
  renderMessages();
  renderChatList();
  updateSendButton();

  document.getElementById('chatInput')?.focus();
}

function deleteChat(id, e) {
  if (e) e.stopPropagation();
  fetch('/api/sessions/' + encodeURIComponent(id), { method: 'DELETE' }).catch(() => {});
  sessions = sessions.filter(s => s.id !== id);
  if (currentSessionId === id) newChat();
  renderChatList();
}

function renderChatList() {
  const el = document.getElementById('chatList');
  if (!el) return;
  const list = sessions;
  el.innerHTML = list.map(s => {
    const active = s.id === currentSessionId ? 'background:var(--bg-surface-alt);' : '';
    const streaming = _chatStreaming[s.id] ? ' 🔄' : '';
    const modeColor = MODE_COLORS[s.provider || s.mode] || '#7aaeE0';
    const timeAgo = _timeAgo(s.updated_at || s.created_at);
    const leaveBg = s.id === currentSessionId ? 'var(--bg-surface-alt)' : 'transparent';
    return `<div onclick="switchToChat('${s.id}')" style="display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;border-radius:8px;${active}" onmouseenter="this.style.background='var(--bg-surface-alt)'" onmouseleave="this.style.background='${leaveBg}'">
      <span style="width:6px;height:6px;border-radius:50%;background:${modeColor};flex-shrink:0;"></span>
      <span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px;">${esc(s.title || 'Untitled')}${streaming}</span>
      <span style="font-size:10px;color:var(--text-muted);flex-shrink:0;">${timeAgo}</span>
      <span onclick="deleteChat('${s.id}', event)" style="font-size:12px;opacity:0.3;cursor:pointer;flex-shrink:0;" onmouseenter="this.style.opacity='1'" onmouseleave="this.style.opacity='0.3'">✕</span>
    </div>`;
  }).join('');
}

function filterChatList(q) {
  renderChatList();
}

function renderMessages() {
  const area = document.getElementById('messagesArea');
  area.innerHTML = '';
  for (const msg of currentMessages) {
    if (msg.role === 'user') appendUserMessage(msg.content);
    else if (msg.role === 'assistant') appendAssistantMessage(msg.content, msg.thinking, msg.tool_calls);
  }
  scrollToBottom();
}
