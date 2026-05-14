// ===== CHATBOX INTELLIGENCE: History, Trie, @-files =====

// ── Message History (Up/Down arrows) ────────────────────────────────
let _msgHistory = [];  // most recent first
let _msgHistoryIdx = -1;  // -1 = not browsing history
let _msgHistoryDraft = '';  // save current draft when entering history

async function _loadHistory() {
  // History is now managed locally in _msgHistory (populated during sendMessage)
  const saved = localStorage.getItem('unified_msg_history');
  if (saved) {
    try {
      _msgHistory = JSON.parse(saved);
      for (const t of _msgHistory) _sentenceTrieInsert(t);
    } catch(e) {}
  }
}

function _handleHistoryNav(el, direction) {
  // direction: -1 = up (older), +1 = down (newer)
  if (_msgHistoryIdx === -1 && direction === -1) {
    // Start browsing: save current draft
    _msgHistoryDraft = el.value;
    _msgHistoryIdx = 0;
    if (_msgHistory.length > 0) {
      el.value = _msgHistory[0];
      autoResize(el);
    }
    return true;
  }
  if (_msgHistoryIdx >= 0) {
    const newIdx = _msgHistoryIdx + (direction === -1 ? 1 : -1);
    if (newIdx < 0) {
      // Back to draft
      _msgHistoryIdx = -1;
      el.value = _msgHistoryDraft;
      autoResize(el);
      return true;
    }
    if (newIdx < _msgHistory.length) {
      _msgHistoryIdx = newIdx;
      el.value = _msgHistory[newIdx];
      autoResize(el);
      return true;
    }
  }
  return false;
}

// ── Sentence Trie — stores full sentences, searches by prefix ──────
const _sentenceTrie = {};

function _sentenceTrieInsert(sentence) {
  if (!sentence || sentence.length < 2) return;
  let node = _sentenceTrie;
  for (const ch of sentence.toLowerCase()) {
    if (!node[ch]) node[ch] = {};
    node = node[ch];
  }
  node._end = true;
  node._sentence = sentence;  // store original casing
}

function _sentenceTrieSearch(prefix, limit = 5) {
  if (!prefix || prefix.length < 1) return [];
  let node = _sentenceTrie;
  for (const ch of prefix.toLowerCase()) {
    if (!node[ch]) return [];
    node = node[ch];
  }
  // BFS to collect all sentences under this prefix
  const results = [];
  const queue = [node];
  while (queue.length > 0 && results.length < limit) {
    const n = queue.shift();
    if (n._end && n._sentence && n._sentence.toLowerCase() !== prefix.toLowerCase()) {
      results.push(n._sentence);
    }
    for (const k of Object.keys(n)) {
      if (k[0] !== '_') queue.push(n[k]);
    }
  }
  return results;
}

// ── Ghost Text State ────────────────────────────────────────────────
let _ghostSuggestion = '';  // the full suggested sentence
let _ghostTarget = null;

function _getGhostOverlay(el) {
  return document.getElementById(el.id === 'welcomeInput' ? 'welcomeGhost' : 'chatGhost');
}

function _showGhostText(el, fullSentence) {
  const overlay = _getGhostOverlay(el);
  if (!overlay) return;
  const typed = el.value;
  // The completion is the part after what's typed
  const completion = fullSentence.substring(typed.length);
  if (!completion) { _hideGhostText(el); return; }
  _ghostSuggestion = fullSentence;
  _ghostTarget = el;
  overlay.innerHTML = '<span class="ghost-typed">' + esc(typed) + '</span><span class="ghost-completion">' + esc(completion) + '</span>';
}

function _hideGhostText(el) {
  const overlay = _getGhostOverlay(el || _ghostTarget || document.getElementById('chatInput'));
  if (overlay) overlay.innerHTML = '';
  _ghostSuggestion = '';
  _ghostTarget = null;
}

function _acceptGhostText(el) {
  if (!_ghostSuggestion) return false;
  el.value = _ghostSuggestion;
  _hideGhostText(el);
  autoResize(el);
  el.focus();
  return true;
}

// ── Suggestion Dropdown (for @-file only now) ───────────────────────
let _suggestMode = 'none';  // 'none' | 'file'
let _suggestItems = [];
let _suggestActiveIdx = -1;
let _suggestTarget = null;
let _fileSearchTimer = null;

function _getSuggestDropdown(el) {
  const isWelcome = el.id === 'welcomeInput';
  return document.getElementById(isWelcome ? 'welcomeSuggest' : 'chatSuggest');
}

function _showSuggestions(el, items, mode) {
  const dropdown = _getSuggestDropdown(el);
  _suggestMode = mode;
  _suggestItems = items;
  _suggestActiveIdx = -1;
  _suggestTarget = el;

  if (!items.length) {
    dropdown.classList.remove('visible');
    _suggestMode = 'none';
    return;
  }

  dropdown.innerHTML = items.map((item, i) => {
    if (mode === 'file') {
      const name = item.split('/').pop();
      const dir = item.substring(0, item.length - name.length);
      return '<div class="suggest-item suggest-file' + (i === _suggestActiveIdx ? ' active' : '') + '" data-idx="' + i + '">' +
        '<span class="icon">📄</span>' +
        '<span class="text"><span style="opacity:0.5">' + esc(dir) + '</span>' + esc(name) + '</span></div>';
    } else {
      return '<div class="suggest-item suggest-word' + (i === _suggestActiveIdx ? ' active' : '') + '" data-idx="' + i + '">' +
        '<span class="icon">✦</span>' +
        '<span class="text">' + esc(item) + '</span></div>';
    }
  }).join('');

  dropdown.querySelectorAll('.suggest-item').forEach(el => {
    el.addEventListener('mousedown', (e) => {
      e.preventDefault();
      _selectSuggestion(parseInt(el.dataset.idx));
    });
  });

  dropdown.classList.add('visible');
}

function _hideSuggestions(el) {
  const dropdown = _getSuggestDropdown(el || _suggestTarget || document.getElementById('chatInput'));
  dropdown.classList.remove('visible');
  _suggestMode = 'none';
  _suggestItems = [];
  _suggestActiveIdx = -1;
}

function _navigateSuggestion(direction) {
  if (!_suggestItems.length) return false;
  _suggestActiveIdx += direction;
  if (_suggestActiveIdx < 0) _suggestActiveIdx = _suggestItems.length - 1;
  if (_suggestActiveIdx >= _suggestItems.length) _suggestActiveIdx = 0;

  const dropdown = _getSuggestDropdown(_suggestTarget);
  dropdown.querySelectorAll('.suggest-item').forEach((el, i) => {
    el.classList.toggle('active', i === _suggestActiveIdx);
    if (i === _suggestActiveIdx) el.scrollIntoView({ block: 'nearest' });
  });
  return true;
}

function _selectSuggestion(idx) {
  if (idx < 0 || idx >= _suggestItems.length) idx = _suggestActiveIdx;
  if (idx < 0) idx = 0;
  const item = _suggestItems[idx];
  const el = _suggestTarget;

  if (_suggestMode === 'file') {
    const val = el.value;
    const cursor = el.selectionStart;
    let atPos = val.lastIndexOf('@', cursor - 1);
    if (atPos < 0) atPos = 0;
    const before = val.substring(0, atPos);
    const after = val.substring(cursor);
    el.value = before + '@' + item + ' ' + after;
    const newPos = before.length + 1 + item.length + 1;
    el.selectionStart = el.selectionEnd = newPos;
  }

  _hideSuggestions(el);
  _hideGhostText(el);
  autoResize(el);
  el.focus();
}

function _handleInput(el) {
  const val = el.value;
  const cursor = el.selectionStart;

  // Check for @-file mode
  let atPos = -1;
  for (let i = cursor - 1; i >= 0; i--) {
    if (val[i] === '@') { atPos = i; break; }
    if (val[i] === ' ' || val[i] === '\n') break;
  }

  if (atPos >= 0 && (atPos === 0 || /[\s\n]/.test(val[atPos - 1]))) {
    const query = val.substring(atPos + 1, cursor);
    if (query.length >= 1) {
      clearTimeout(_fileSearchTimer);
      _fileSearchTimer = setTimeout(async () => {
        try {
          const resp = await fetch('/api/files?q=' + encodeURIComponent(query) + '&limit=5');
          const files = await resp.json();
          _showSuggestions(el, files, 'file');
        } catch(e) { _hideSuggestions(el); }
      }, 200);
      _hideGhostText(el);
      return;
    }
  }

  // Sentence ghost text — search Trie for full sentence match
  _hideSuggestions(el);
  if (val.length >= 2 && cursor === val.length) {
    const matches = _sentenceTrieSearch(val, 1);
    if (matches.length > 0) {
      _showGhostText(el, matches[0]);
      return;
    }
  }
  _hideGhostText(el);
}

// ===== EVENT LISTENERS =====
['welcomeInput', 'chatInput'].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener('input', () => { autoResize(el); _handleInput(el); });
  el.addEventListener('keydown', (e) => {
    // File suggestion dropdown navigation
    if (_suggestMode !== 'none') {
      if (e.key === 'ArrowDown') { e.preventDefault(); _navigateSuggestion(1); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); _navigateSuggestion(-1); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && _suggestActiveIdx >= 0)) {
        e.preventDefault(); _selectSuggestion(_suggestActiveIdx >= 0 ? _suggestActiveIdx : 0); return;
      }
      if (e.key === 'Escape') { e.preventDefault(); _hideSuggestions(el); return; }
    }

    // Ghost text Tab acceptance
    if (e.key === 'Tab' && _ghostSuggestion) {
      e.preventDefault();
      _acceptGhostText(el);
      return;
    }

    // Escape clears ghost text
    if (e.key === 'Escape' && _ghostSuggestion) {
      _hideGhostText(el);
    }

    // History navigation (only when no suggestions shown and no ghost)
    if (e.key === 'ArrowUp' && !e.shiftKey && _suggestMode === 'none') {
      if (el.selectionStart === 0 || _msgHistoryIdx >= 0) {
        if (_handleHistoryNav(el, -1)) { e.preventDefault(); _hideGhostText(el); return; }
      }
    }
    if (e.key === 'ArrowDown' && !e.shiftKey && _suggestMode === 'none') {
      if (_msgHistoryIdx >= 0) {
        if (_handleHistoryNav(el, 1)) { e.preventDefault(); _hideGhostText(el); return; }
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      _hideGhostText(el);
      if (isStreaming) return;
      if (el.value.trim()) sendMessage(el.value.trim());
    }
  });
  el.addEventListener('blur', () => { setTimeout(() => { _hideSuggestions(el); _hideGhostText(el); }, 150); });
});

document.getElementById('sendBtnWelcome').addEventListener('click', () => {
  if (isStreaming) { stopGeneration(); return; }
  const t = document.getElementById('welcomeInput').value.trim();
  if (t) sendMessage(t);
});
document.getElementById('sendBtnChat').addEventListener('click', () => {
  if (isStreaming) { stopGeneration(); return; }
  const t = document.getElementById('chatInput').value.trim();
  if (t) sendMessage(t);
});

// File upload listeners
document.getElementById('welcomeFileInput').addEventListener('change', (e) => { handleFileUpload('welcome', e.target.files); e.target.value = ''; });
document.getElementById('chatFileInput').addEventListener('change', (e) => { handleFileUpload('chat', e.target.files); e.target.value = ''; });

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); newChat(); }
  if (e.key === 'Escape') closeSettings();
});

