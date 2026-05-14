
// ===== MESSAGE RENDERING =====
function appendUserMessage(text) {
  const area = document.getElementById('messagesArea');
  const div = document.createElement('div');
  div.className = 'message-user';
  const displayText = typeof text === 'string' ? text : (text.find ? text.find(p => p.type === 'text')?.text || '' : '');
  div.innerHTML = '<div class="msg-bubble">' + esc(displayText) + '</div>';
  area.appendChild(div);
  scrollToBottom();
}

function createAssistantMessageEl(targetArea) {
  const area = targetArea || document.getElementById('messagesArea');
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.innerHTML = '<div class="thinking-block" id="currentThinking" style="display:none;">' +
    '<div class="thinking-header" onclick="toggleCollapse(this)">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' +
    '<span class="thinking-label">Thinking...</span>' +
    '<span class="thinking-dots"><span>\u00B7</span><span>\u00B7</span><span>\u00B7</span></span></div>' +
    '<div class="thinking-body" id="currentThinkingBody"></div></div>' +
    '<div class="tool-calls-container" id="currentToolCalls"></div>' +
    '<div class="msg-content" id="currentContent"></div>';
  area.appendChild(div);
  if (!targetArea) scrollToBottom();
  return div;
}

function appendAssistantMessage(content, reasoning, toolCalls) {
  const area = document.getElementById('messagesArea');
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  let html = '';
  if (reasoning) {
    html += '<div class="thinking-block"><div class="thinking-header collapsed" onclick="toggleCollapse(this)">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' +
      '<span>Thought for a moment</span></div>' +
      '<div class="thinking-body collapsed">' + esc(reasoning) + '</div></div>';
  }
  if (toolCalls && toolCalls.length) {
    for (const tc of toolCalls) html += renderToolBlock(tc, true);
  }
  if (content) html += '<div class="msg-content">' + renderMarkdown(content) + '</div>';
  html += msgActionButtons(content);
  div.innerHTML = html;
  area.appendChild(div);
  scrollToBottom();
}

function msgActionButtons(content) {
  const safeId = 'msg-' + Math.random().toString(36).substr(2,8);
  window['_msgContent_' + safeId] = content || '';
  return '<div class="msg-actions">' +
    '<button class="msg-action-btn" title="Copy" onclick="navigator.clipboard.writeText(window[\'_msgContent_' + safeId + '\']).then(()=>showToast(\'Copied!\'))">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>' +
    '<button class="msg-action-btn" title="Thumbs up"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg></button>' +
    '<button class="msg-action-btn" title="Thumbs down"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg></button>' +
    '<button class="msg-action-btn" title="Retry"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/></svg></button>' +
    '</div>';
}

function renderToolBlock(tc, collapsed = false) {
  const icon = TOOL_ICONS[tc.name] || TOOL_ICONS.default;
  const cls = collapsed ? 'collapsed' : '';
  const statusCls = tc.error || tc.is_error ? 'error' : 'done';
  const statusText = tc.error || tc.is_error ? '\u2717 Error' : '\u2713 Done';
  const args = tc.args || tc.arguments || tc.input || '';
  const result = tc.result || tc.output || '';
  return '<div class="tool-block"><div class="tool-header ' + cls + '" onclick="toggleCollapse(this)">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' +
    '<span class="tool-icon">' + icon + '</span><span class="tool-name">' + esc(tc.name) + '</span>' +
    '<span class="tool-status ' + statusCls + '">' + statusText + '</span></div>' +
    '<div class="tool-body ' + cls + '"><div class="tool-section"><div class="tool-section-label">Arguments</div>' +
    '<pre>' + esc(typeof args === 'string' ? args : JSON.stringify(args, null, 2)) + '</pre></div>' +
    (result ? '<div class="tool-section"><div class="tool-section-label">Result</div>' +
    '<pre>' + esc(typeof result === 'string' ? result : JSON.stringify(result, null, 2)) + '</pre></div>' : '') +
    '</div></div>';
}

// ===== UNIFIED STREAMING =====
async function sendMessage(text) {
  if (!text.trim() || isStreaming) return;

  // Save to message history
  _msgHistory.unshift(text);
  if (_msgHistory.length > 500) _msgHistory.length = 500;
  _msgHistoryIdx = -1;
  _msgHistoryDraft = '';
  _sentenceTrieInsert(text);
  try { localStorage.setItem('unified_msg_history', JSON.stringify(_msgHistory.slice(0, 200))); } catch(e) {}

  // Gather uploaded files
  const ctx = currentSessionId ? 'chat' : 'welcome';
  const files = [...uploadedFiles[ctx]];
  uploadedFiles[ctx] = [];
  renderFileChips(ctx);

  if (!currentSessionId) {
    await createSession(text);
    document.getElementById('welcomeScreen').classList.add('hidden');
    document.getElementById('messagesArea').classList.add('active');
    document.getElementById('chatInputArea').style.display = '';
    document.getElementById('chatHeader').style.display = '';
    document.getElementById('chatTitleText').textContent = text.substring(0, 50) + (text.length > 50 ? '...' : '');
  }

  // Build user content (multimodal if images)
  let userContent;
  const imageFiles = files.filter(f => f.type === 'image');
  const textFiles = files.filter(f => f.type === 'text');
  let fullText = text;
  if (textFiles.length) {
    fullText += '\n\n' + textFiles.map(f => '--- ' + f.name + ' ---\n' + f.data).join('\n\n');
  }
  if (imageFiles.length) {
    userContent = [{ type: 'text', text: fullText }];
    for (const img of imageFiles) {
      userContent.push({ type: 'image_url', image_url: { url: img.data } });
    }
  } else {
    userContent = fullText;
  }

  currentMessages.push({ role: 'user', content: userContent });
  appendUserMessage(userContent);

  document.getElementById('welcomeInput').value = '';
  document.getElementById('chatInput').value = '';
  autoResize(document.getElementById('chatInput'));

  await streamUnified();
}

// Single unified streaming function for ALL providers
async function streamUnified() {
  const streamSessionId = currentSessionId;
  const isActive = () => currentSessionId === streamSessionId;
  if (isActive()) { isStreaming = true; stopRequested = false; updateSendButton(); }
  const myAbort = new AbortController();
  if (isActive()) abortController = myAbort;
  _chatStreaming[streamSessionId] = { abortController: myAbort, stopRequested: false };
  const _detachedArea = document.createElement('div');
  const getTargetArea = () => isActive() ? null : _detachedArea;

  const msgEl = createAssistantMessageEl(getTargetArea());
  const thinkingBlock = msgEl.querySelector('#currentThinking') || msgEl.querySelector('.thinking-block');
  const thinkingBody = msgEl.querySelector('#currentThinkingBody') || msgEl.querySelector('.thinking-body');
  const thinkingLabel = msgEl.querySelector('.thinking-label');
  const thinkingDots = msgEl.querySelector('.thinking-dots');
  const contentEl = msgEl.querySelector('#currentContent') || msgEl.querySelector('.msg-content');
  const toolCallsEl = msgEl.querySelector('#currentToolCalls') || msgEl.querySelector('.tool-calls-container');
  const safeScroll = () => { if (isActive()) scrollToBottom(); };

  let content = '', reasoning = '';
  let thinkingStartTime = Date.now();
  let costInfo = null;
  const _toolDivs = {};
  const _toolCalls = [];

  // Build messages for API — send only the latest user message
  // Server reconstructs full history from DB (source of truth)
  const provider = MODE_TO_PROVIDER[currentMode] || 'vllm';
  const lastUserMsg = currentMessages.filter(m => m.role === 'user').slice(-1);
  const apiMessages = lastUserMsg.map(m => ({ role: m.role, content: m.content }));

  const sampling = SAMPLING_MODES[currentSamplingMode];

  try {
    const body = {
      provider,
      mode: currentMode,
      model: currentModelId,
      messages: apiMessages,
      system_prompt: SYSTEM_PROMPTS[currentMode],
      temperature: sampling.temperature,
      top_p: sampling.top_p,
      top_k: sampling.top_k,
      presence_penalty: sampling.presence_penalty,
      repetition_penalty: sampling.repetition_penalty,
      enable_thinking: sampling.thinking,
    };
    if (streamSessionId && !streamSessionId.startsWith('temp-')) {
      body.session_id = streamSessionId;
    }

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: myAbort.signal,
    });

    if (!response.ok) throw new Error('API error ' + response.status + ': ' + await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (data === '[DONE]') continue;
        try {
          const chunk = JSON.parse(data);

          if (chunk.type === 'session') {
            // Server assigned/confirmed session_id
            if (chunk.session_id && (!currentSessionId || currentSessionId.startsWith('temp-'))) {
              const previousId = currentSessionId;
              currentSessionId = chunk.session_id;
              _saveSessionMode(chunk.session_id, currentMode);
              const tempIndex = previousId ? sessions.findIndex(s => s.id === previousId) : -1;
              const existing = sessions.find(s => s.id === chunk.session_id);
              if (tempIndex >= 0) {
                sessions[tempIndex] = { ...(sessions[tempIndex] || {}), id: chunk.session_id, provider, mode: currentMode, model: currentModelId, updated_at: new Date().toISOString() };
              } else if (!existing) {
                sessions.unshift({ id: chunk.session_id, title: 'New Chat', mode: currentMode, provider, model: currentModelId, created_at: Date.now(), updated_at: new Date().toISOString() });
              }
              sessions = sessions.filter((session, index, arr) => arr.findIndex(other => other.id === session.id) === index);
              renderChatList();
            }
          } else if (chunk.type === 'delta') {
            // Remove processing indicator when real content starts
            contentEl.querySelector('.processing-indicator')?.remove();
            // Finalize thinking if transitioning
            if (thinkingBlock.style.display !== 'none' && !thinkingBlock.dataset.done) {
              thinkingBlock.dataset.done = '1';
              const secs = ((Date.now() - thinkingStartTime) / 1000).toFixed(0);
              thinkingLabel.textContent = 'Thought for ' + secs + 's';
              thinkingDots.style.display = 'none';
              thinkingBlock.querySelector('.thinking-header').classList.add('collapsed');
              thinkingBody.classList.add('collapsed');
            }
            content += chunk.content;
            contentEl.innerHTML = renderMarkdown(content);
            safeScroll();
          } else if (chunk.type === 'thinking_delta') {
            if (thinkingBlock.style.display === 'none') {
              thinkingBlock.style.display = '';
              thinkingStartTime = Date.now();
            }
            // If thinking was finalized (from a prior round), reopen it
            if (thinkingBlock.dataset.done) {
              delete thinkingBlock.dataset.done;
              thinkingLabel.textContent = 'Thinking...';
              if (thinkingDots) thinkingDots.style.display = '';
              thinkingBlock.querySelector('.thinking-header').classList.remove('collapsed');
              thinkingBody.classList.remove('collapsed');
            }
            reasoning += chunk.content;
            thinkingBody.textContent = reasoning;
            thinkingBody.scrollTop = thinkingBody.scrollHeight;
            safeScroll();
          } else if (chunk.type === 'tool_start') {
            console.debug('[tool_start]', chunk.tool_call_id, chunk.name);
            // Skip internal tools like report_intent
            if (chunk.name === 'report_intent') {
              _toolDivs['_skip_' + chunk.tool_call_id] = true;
            } else {
              const icon = TOOL_ICONS[chunk.name] || TOOL_ICONS.default;
              const toolDiv = document.createElement('div');
              toolDiv.innerHTML = '<div class="tool-block"><div class="tool-header" onclick="toggleCollapse(this)">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' +
                '<span class="tool-icon">' + icon + '</span><span class="tool-name">' + esc(chunk.name) + '</span>' +
                '<span class="tool-status running"><span class="tool-spinner"></span> Running</span></div>' +
                '<div class="tool-body"><div class="tool-section"><div class="tool-section-label">Arguments</div>' +
                '<pre class="tool-args-pre">' + esc(chunk.arguments ? (typeof chunk.arguments === 'string' ? chunk.arguments : JSON.stringify(chunk.arguments, null, 2)) : '...') + '</pre></div>' +
                '<div class="tool-section"><div class="tool-section-label">Result</div>' +
                '<pre class="tool-result-pre" style="color:var(--text-muted)">Executing...</pre></div></div></div>';
              toolCallsEl.appendChild(toolDiv);
              _toolDivs[chunk.tool_call_id] = { div: toolDiv, name: chunk.name, inputBuf: '' };
              safeScroll();
            }
          } else if (chunk.type === 'tool_input_delta') {
            const tid = chunk.tool_call_id || Object.keys(_toolDivs).filter(k => !k.startsWith('_skip_')).pop();
            if (tid && _toolDivs[tid] && !_toolDivs[tid].div === undefined) {}
            if (tid && _toolDivs[tid] && _toolDivs[tid].div) {
              _toolDivs[tid].inputBuf += chunk.content;
              const pre = _toolDivs[tid].div.querySelector('.tool-args-pre');
              if (pre) pre.textContent = _toolDivs[tid].inputBuf;
            }
          } else if (chunk.type === 'tool_progress') {
            const td = _toolDivs[chunk.tool_call_id];
            if (td && td.div) {
              const pre = td.div.querySelector('.tool-result-pre');
              if (pre) pre.textContent = chunk.message || chunk.content || 'Working...';
            }
          } else if (chunk.type === 'tool_complete') {
            console.debug('[tool_complete]', chunk.tool_call_id, chunk.name, 'known_ids:', Object.keys(_toolDivs));
            const td = _toolDivs[chunk.tool_call_id];
            if (td && td.div) {
              const statusEl = td.div.querySelector('.tool-status');
              const pre = td.div.querySelector('.tool-result-pre');
              if (chunk.is_error) {
                statusEl.className = 'tool-status error';
                statusEl.innerHTML = '\u2717 Error';
                if (pre) { pre.textContent = chunk.result || chunk.content || '[error]'; pre.style.color = 'var(--red)'; }
              } else {
                statusEl.className = 'tool-status done';
                statusEl.innerHTML = '\u2713 Done';
                if (pre) { pre.textContent = chunk.result || chunk.content || '[ok]'; pre.style.color = ''; }
              }
              td.div.querySelector('.tool-header').classList.add('collapsed');
              td.div.querySelector('.tool-body').classList.add('collapsed');
              _toolCalls.push({ name: td.name, args: td.inputBuf, result: chunk.result || chunk.content || '', error: chunk.is_error || false });
            }
            safeScroll();
          } else if (chunk.type === 'compaction') {
            showToast('Context compacted — older messages summarized');
          } else if (chunk.type === 'processing') {
            // Model is processing tool results — show activity in content area
            if (!contentEl.querySelector('.processing-indicator')) {
              const ind = document.createElement('span');
              ind.className = 'processing-indicator';
              ind.style.cssText = 'opacity:0.5;font-size:13px;font-style:italic;';
              ind.textContent = ' Processing...';
              contentEl.appendChild(ind);
            }
            // Reset thinking block so round 2 thinking shows fresh
            if (thinkingBlock.dataset.done) {
              delete thinkingBlock.dataset.done;
              thinkingBlock.style.display = 'none';
              thinkingLabel.textContent = 'Thinking...';
              if (thinkingDots) thinkingDots.style.display = '';
              thinkingBlock.querySelector('.thinking-header').classList.remove('collapsed');
              thinkingBody.classList.remove('collapsed');
            }
          } else if (chunk.type === 'done') {
            // Remove processing indicator if present
            contentEl.querySelector('.processing-indicator')?.remove();
            // Final metadata from server
            costInfo = chunk;
            // Finalize thinking
            if (reasoning && thinkingBlock.style.display !== 'none' && !thinkingBlock.dataset.done) {
              const secs = ((Date.now() - thinkingStartTime) / 1000).toFixed(0);
              thinkingLabel.textContent = 'Thought for ' + secs + 's';
              thinkingDots.style.display = 'none';
              thinkingBlock.querySelector('.thinking-header').classList.add('collapsed');
              thinkingBody.classList.add('collapsed');
            }
            // Fallback: if model produced no content AND no tool calls, surface the thinking as the answer
            if (!content && Object.keys(_toolDivs).filter(k => !k.startsWith('_skip_')).length === 0) {
              if (reasoning) {
                content = reasoning;
                contentEl.innerHTML = renderMarkdown(content);
                // Keep thinking expanded for transparency
                thinkingBlock.querySelector('.thinking-header').classList.remove('collapsed');
                thinkingBody.classList.remove('collapsed');
              } else {
                content = '*[No response — model returned empty. Try rephrasing or retry.]*';
                contentEl.innerHTML = renderMarkdown(content);
              }
            }
          } else if (chunk.type === 'error') {
            content = '**Error:** ' + (chunk.content || chunk.message || 'Unknown error');
            contentEl.innerHTML = renderMarkdown(content);
          }
        } catch(e) {}
      }
    }
  } catch(e) {
    if (e.name === 'AbortError') {
      content += '\n\n*[Generation stopped]*';
    } else {
      content = '**Error:** ' + e.message;
    }
    contentEl.innerHTML = renderMarkdown(content);
  }

  // Show cost badge if available
  if (costInfo && costInfo.cost_usd != null) {
    const badge = document.createElement('div');
    badge.style.cssText = 'font-size:11px;opacity:0.4;text-align:right;margin-top:4px;';
    badge.textContent = '$' + Number(costInfo.cost_usd).toFixed(4);
    if (costInfo.input_tokens || costInfo.output_tokens) {
      badge.textContent += ' (' + (costInfo.input_tokens || 0) + ' in / ' + (costInfo.output_tokens || 0) + ' out)';
    }
    msgEl.appendChild(badge);
  }

  // Save to local state (server already persisted)
  currentMessages.push({ role: 'assistant', content, thinking: reasoning, tool_calls: _toolCalls });

  const actionsDiv = document.createElement('div');
  actionsDiv.innerHTML = msgActionButtons(content);
  msgEl.appendChild(actionsDiv.firstChild);

  msgEl.querySelectorAll('[id^="current"]').forEach(el => el.removeAttribute('id'));
  if (isActive()) { isStreaming = false; if (abortController === myAbort) abortController = null; }
  delete _chatStreaming[streamSessionId];
  delete _chatDomCache[streamSessionId];
  if (isActive()) { updateSendButton(); }
  await loadSessions();
  renderChatList();
  safeScroll();
  if (isActive()) document.getElementById('chatInput')?.focus();
}

function stopGeneration() {
  stopRequested = true;
  if (abortController) {
    try { abortController.abort(); } catch(e) {}
    abortController = null;
  }
  isStreaming = false;
  if (currentSessionId && _chatStreaming[currentSessionId]) {
    _chatStreaming[currentSessionId].stopRequested = true;
    try { _chatStreaming[currentSessionId].abortController.abort(); } catch(e) {}
  }
  updateSendButton();
}

