// ===== UI HELPERS =====
function toggleSidebar() { document.getElementById('sidebar').classList.toggle('collapsed'); }

function toggleCollapse(header) {
  header.classList.toggle('collapsed');
  header.nextElementSibling.classList.toggle('collapsed');
}

function scrollToBottom() {
  const area = document.getElementById('messagesArea');
  requestAnimationFrame(() => { area.scrollTop = area.scrollHeight; });
}

function updateSendButton() {
  ['sendBtnWelcome', 'sendBtnChat'].forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (isStreaming) {
      btn.classList.add('streaming');
      btn.innerHTML = '<div class="stop-icon"></div>';
      btn.onclick = stopGeneration;
    } else {
      btn.classList.remove('streaming');
      btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
      btn.onclick = null;
    }
  });
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
  const isW = el.id === 'welcomeInput';
  const btn = document.getElementById(isW ? 'sendBtnWelcome' : 'sendBtnChat');
  if (!isStreaming) btn.classList.toggle('active', el.value.trim().length > 0);
}

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function copyCode(id) {
  const el = document.getElementById(id);
  if (el) navigator.clipboard.writeText(el.textContent);
  showToast('Copied!');
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2000);
}

function sendQuickAction(text) {
  document.getElementById('welcomeInput').value = text;
  sendMessage(text);
}

