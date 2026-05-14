// ===== SAMPLING =====
function setSamplingMode(mode) {
  currentSamplingMode = mode;
  localStorage.setItem('unified_sampling', mode);
  updateSamplingDisplay();
}

function updateSamplingDisplay() {
  const m = SAMPLING_MODES[currentSamplingMode];
  document.querySelectorAll('.sampling-badge').forEach(b => b.textContent = m.label);
  const selEl = document.getElementById('samplingModeSelect');
  if (selEl) selEl.value = currentSamplingMode;
  const params = [];
  if (m.temperature !== undefined) params.push('temp: ' + m.temperature);
  if (m.top_p !== undefined) params.push('top_p: ' + m.top_p);
  if (m.top_k !== undefined) params.push('top_k: ' + m.top_k);
  if (m.presence_penalty) params.push('pres_pen: ' + m.presence_penalty);
  if (m.repetition_penalty) params.push('rep_pen: ' + m.repetition_penalty);
  params.push('thinking: ' + (m.thinking ? 'on' : 'off'));
  const pd = document.getElementById('paramDisplay');
  if (pd) pd.textContent = params.join(' | ');
}

// ===== SETTINGS =====
function openSettings() {
  document.getElementById('settingsOverlay').classList.add('open');
  updateSamplingDisplay();
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b.dataset.theme === currentTheme));
}
function closeSettings() {
  document.getElementById('settingsOverlay').classList.remove('open');
}

// ===== FILE UPLOAD =====
function triggerUpload(ctx) {
  const el = document.getElementById(ctx + 'FileInput');
  if (el) el.click();
}

function handleFileUpload(ctx, files) {
  for (const file of files) {
    const reader = new FileReader();
    if (file.type.startsWith('image/')) {
      reader.onload = (e) => {
        uploadedFiles[ctx].push({ name: file.name, data: e.target.result, type: 'image' });
        renderFileChips(ctx);
      };
      reader.readAsDataURL(file);
    } else {
      reader.onload = (e) => {
        uploadedFiles[ctx].push({ name: file.name, data: e.target.result, type: 'text' });
        renderFileChips(ctx);
      };
      reader.readAsText(file);
    }
  }
}

function renderFileChips(ctx) {
  const el = document.getElementById(ctx + 'FileChips');
  if (!el) return;
  const files = uploadedFiles[ctx];
  el.innerHTML = files.map((f, i) => {
    const preview = f.type === 'image'
      ? '<img src="' + f.data + '" style="width:20px;height:20px;object-fit:cover;border-radius:3px;margin-right:4px;">'
      : '<span style="margin-right:4px;">📎</span>';
    return '<span class="file-chip">' + preview + esc(f.name) +
      '<span onclick="removeFile(\'' + ctx + '\',' + i + ')" style="cursor:pointer;margin-left:4px;opacity:0.6;">✕</span></span>';
  }).join('');
}

function removeFile(ctx, idx) {
  uploadedFiles[ctx].splice(idx, 1);
  renderFileChips(ctx);
}

