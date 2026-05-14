// ===== THEME =====

// ===== THEME =====
function setTheme(theme) {
  currentTheme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('unified_theme', theme);
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b.dataset.theme === theme));
}

// ===== MODE =====
async function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  const placeholders = {
    chat: ['How can I help you today?', 'Reply to Kivi...'],
    kivi: ['Ask Kivi to help with code...', 'Ask Kivi...'],
    copilot: ['Ask Copilot anything...', 'Ask Copilot...'],
    'qwen-copilot': ['Ask QCopilot anything...', 'Ask QCopilot...'],
    claude: ['Ask Claude anything...', 'Ask Claude...'],
    'qwen-claude': ['Ask QClaude anything...', 'Ask QClaude...'],
  };
  const [ph, phChat] = placeholders[mode] || placeholders.chat;
  document.getElementById('welcomeInput').placeholder = ph;
  document.getElementById('chatInput').placeholder = phChat;
  await updateModelSelectors();
  await syncCurrentSessionConfig(mode, currentModelId);
}

async function selectModel(modelId) {
  currentModelId = modelId;
  document.querySelectorAll('.model-selector').forEach(s => s.value = modelId);
  await syncCurrentSessionConfig(currentMode, modelId);
}

async function loadModelsForProvider(provider) {
  if (_providerModels[provider]) return _providerModels[provider];
  try {
    const resp = await fetch('/api/models/' + encodeURIComponent(provider));
    const models = await resp.json();
    if (Array.isArray(models) && models.length > 0) {
      // Ensure friendly display name (last path component)
      for (const m of models) {
        if (!m.name || m.name === m.id) {
          m.name = m.id.includes('/') ? m.id.split('/').pop() : m.id;
        }
      }
      _providerModels[provider] = models;
      return models;
    }
  } catch(e) { console.warn('Failed to load models for', provider, e); }
  return [];
}

async function updateModelSelectors() {
  const provider = MODE_TO_PROVIDER[currentMode] || 'vllm';
  const models = await loadModelsForProvider(provider);

  document.querySelectorAll('.model-selector').forEach(sel => {
    sel.innerHTML = '';
    if (models.length > 0) {
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name || (m.id.includes('/') ? m.id.split('/').pop() : m.id);
        sel.appendChild(opt);
      }
      const preferred = models.find(m => m.id === currentModelId) || models[0];
      if (preferred) currentModelId = preferred.id;
    } else {
      sel.innerHTML = '<option value="default">Default Model</option>';
      currentModelId = 'default';
    }
    sel.value = currentModelId;
  });
}

async function syncCurrentSessionConfig(mode = currentMode, model = currentModelId) {
  if (!currentSessionId || currentSessionId.startsWith('temp-') || isStreaming) return;
  const provider = MODE_TO_PROVIDER[mode] || 'vllm';
  const session = getSession(currentSessionId);
  if (!session) return;
  const currentProvider = session.provider || MODE_TO_PROVIDER[session.mode] || 'vllm';
  if (currentProvider === provider && session.model === model) return;
  try {
    await fetch('/api/sessions/' + encodeURIComponent(currentSessionId) + '/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    });
    session.provider = provider;
    session.model = model;
    session.mode = mode;
    session.updated_at = new Date().toISOString();
    renderChatList();
  } catch (e) {
    console.warn('Failed to sync session config:', e);
  }
}

