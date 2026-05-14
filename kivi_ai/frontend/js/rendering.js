// ===== INIT THEME =====
document.documentElement.setAttribute('data-theme', currentTheme);

// ===== MARKED CONFIG =====
marked.setOptions({
  highlight: function(code, lang) {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
    return hljs.highlightAuto(code).value;
  },
  breaks: true, gfm: true,
});

const renderer = new marked.Renderer();
renderer.code = function(obj) {
  const code = typeof obj === 'object' ? obj.text : obj;
  const lang = typeof obj === 'object' ? (obj.lang || '') : (arguments[1] || '');

  // SVG rendering — show rendered SVG + collapsible source
  if (lang === 'svg' || (lang === '' && code.trimStart().startsWith('<svg'))) {
    const id = 'svg-' + Math.random().toString(36).substr(2, 9);
    const codeId = 'code-' + Math.random().toString(36).substr(2, 9);
    const highlighted = hljs.highlight(code, { language: 'xml' }).value;
    return '<div class="svg-render-block">' +
      '<div class="svg-render-preview" id="' + id + '">' + code + '</div>' +
      '<div class="svg-render-actions">' +
        '<button class="copy-btn" onclick="copyCode(\'' + codeId + '\')">Copy SVG</button>' +
        '<button class="copy-btn" onclick="var s=document.getElementById(\'' + codeId + '-wrap\');s.style.display=s.style.display===\'none\'?\'block\':\'none\';this.textContent=s.style.display===\'none\'?\'Show Code\':\'Hide Code\'">Show Code</button>' +
      '</div>' +
      '<pre id="' + codeId + '-wrap" style="display:none;margin-top:8px;"><div class="code-header"><span>svg</span></div><code id="' + codeId + '" class="hljs language-xml">' + highlighted + '</code></pre>' +
    '</div>';
  }

  const highlighted = lang && hljs.getLanguage(lang)
    ? hljs.highlight(code, { language: lang }).value
    : hljs.highlightAuto(code).value;
  const id = 'code-' + Math.random().toString(36).substr(2, 9);
  return '<pre><div class="code-header"><span>' + (lang || 'code') + '</span><button class="copy-btn" onclick="copyCode(\'' + id + '\')">Copy</button></div><code id="' + id + '" class="hljs language-' + lang + '">' + highlighted + '</code></pre>';
};
marked.use({ renderer });

// ── LaTeX rendering with KaTeX ──────────────────────────────────────
function renderLatex(html) {
  if (typeof katex === 'undefined') return html;
  // Block math: $$...$$ (including multiline)
  html = html.replace(/\$\$([\s\S]+?)\$\$/g, function(m, tex) {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); }
    catch(e) { return m; }
  });
  // Inline math: $...$ (not $$, not inside code tags)
  html = html.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)/g, function(m, tex) {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); }
    catch(e) { return m; }
  });
  // \[...\] block math
  html = html.replace(/\\\[([\s\S]+?)\\\]/g, function(m, tex) {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); }
    catch(e) { return m; }
  });
  // \(...\) inline math
  html = html.replace(/\\\(([\s\S]+?)\\\)/g, function(m, tex) {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); }
    catch(e) { return m; }
  });
  return html;
}

function renderMarkdown(text) {
  // Process <render_inline> tags BEFORE markdown parsing (preserve them as placeholders)
  const renderSlots = [];
  text = text.replace(/<render_inline\s+type="(image|video|text|file)"\s+src="([^"]+)"\s*\/?>/gi, function(match, type, filepath) {
    const idx = renderSlots.length;
    const encoded = encodeURIComponent(filepath);
    const fname = filepath.split('/').pop();
    let replacement;
    if (type === 'image') {
      replacement = '<div class="render-block render-image">' +
        '<div class="render-label">📷 ' + fname + '</div>' +
        '<img src="/api/file-preview?path=' + encoded + '" alt="' + fname + '" loading="lazy" onerror="this.parentElement.innerHTML=\'<div class=render-error>⚠️ Could not load: ' + fname + '</div>\'">' +
      '</div>';
    } else if (type === 'video') {
      replacement = '<div class="render-block render-video">' +
        '<div class="render-label">🎬 ' + fname + '</div>' +
        '<video controls preload="metadata" style="max-width:100%;max-height:500px;">' +
          '<source src="/api/file-preview?path=' + encoded + '">' +
          'Video not supported' +
        '</video>' +
      '</div>';
    } else if (type === 'text') {
      replacement = '<div class="render-block render-text">' +
        '<div class="render-label">📄 ' + fname + '</div>' +
        '<pre class="render-text-content">Loading...</pre>' +
      '</div>';
    } else {
      replacement = '<div class="render-block">' +
        '<div class="render-label">📎 <a href="/api/file-preview?path=' + encoded + '" target="_blank">' + fname + '</a></div>' +
      '</div>';
    }
    renderSlots.push(replacement);
    return '%%RENDER_SLOT_' + idx + '%%';
  });

  let html = renderLatex(marked.parse(text));

  // Restore render slots
  html = html.replace(/%%RENDER_SLOT_(\d+)%%/g, (m, idx) => renderSlots[parseInt(idx)] || '');

  // Strip raw <svg> that leaked through markdown as live HTML.
  html = html.replace(/<svg\b[^>]*>[\s\S]*?<\/svg>/gi, function(match, offset, str) {
    const before = str.substring(Math.max(0, offset - 200), offset);
    if (before.includes('svg-render-preview')) return match;
    return '<pre><code>' + match.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</code></pre>';
  });
  return html;
}

