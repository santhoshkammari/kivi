async function init() {
  const hour = new Date().getHours();
  let g = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  document.getElementById('greetingText').textContent = g + ' — Kivi';

  const savedTheme = localStorage.getItem('unified_theme');
  const savedSampling = localStorage.getItem('unified_sampling');
  if (savedTheme) currentTheme = savedTheme;
  if (savedSampling) currentSamplingMode = savedSampling;

  setTheme(currentTheme);
  await setMode(currentMode);
  updateSamplingDisplay();
  await loadSessions();
  await _loadHistory();
  document.getElementById('welcomeInput').focus();
}

init();
