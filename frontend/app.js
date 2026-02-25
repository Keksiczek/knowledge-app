/**
 * app.js – Knowledge App frontend logic
 *
 * No external dependencies. Talks to the FastAPI backend at /api/*.
 * Handles: navigation, drag-and-drop upload, library, summary,
 *          highlights, presentation, and RAG Q&A.
 */

'use strict';

// ── Config ──────────────────────────────────────────────────────────────────
const API = '';  // empty = same origin; change to 'http://localhost:8000' for dev

// ── State ────────────────────────────────────────────────────────────────────
let selectedDocId = null;
let pollingTimers = {};
let allDocs = [];
let _loadingTimer = null;

// ── Utility helpers ──────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function showToast(msg, type = 'info', duration = 3500) {
  const tc = $('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  tc.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'Z');
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function fileIcon(fmt) {
  const icons = { pdf:'📄', docx:'📝', txt:'📃', md:'📋', pptx:'📊' };
  return icons[fmt] || '📁';
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res;
}

async function apiJSON(path, opts = {}) {
  const res = await apiFetch(path, opts);
  return res.json();
}

// ── Health check ──────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = $('health-indicator');
  try {
    const data = await apiJSON('/api/health');
    dot.className = 'health-dot ok';
    dot.title = `Backend OK — ${data.llm_backend} / ${data.db_engine}`;
  } catch {
    dot.className = 'health-dot error';
    dot.title = 'Backend unreachable';
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('hidden', !v.id.endsWith(name)));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  if (name === 'library') loadLibrary();
  if (name === 'settings') { loadOllamaStatus(); refreshModels(); }
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => showView(btn.dataset.view));
});

// ── Drag & Drop upload ────────────────────────────────────────────────────────
const dropZone = $('drop-zone');
const fileInput = $('file-input');

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  handleFiles([...e.dataTransfer.files]);
});
fileInput.addEventListener('change', () => handleFiles([...fileInput.files]));
dropZone.addEventListener('click', e => {
  if (e.target !== fileInput) fileInput.click();
});

function handleFiles(files) {
  if (!files.length) return;
  files.forEach(uploadFile);
}

function addQueueItem(file, docId) {
  const queue = $('upload-queue');
  queue.classList.remove('hidden');
  const el = document.createElement('div');
  el.className = 'upload-item';
  el.id = `qi-${docId}`;
  el.innerHTML = `
    <span class="file-icon">${fileIcon(file.name.split('.').pop())}</span>
    <div class="file-info">
      <div class="file-name">${escapeHtml(file.name)}</div>
      <div class="file-meta">${formatBytes(file.size)}</div>
    </div>
    <span class="status-badge pending">pending</span>`;
  queue.prepend(el);
  return el;
}

function updateQueueItem(docId, status) {
  const el = $(`qi-${docId}`);
  if (!el) return;
  const badge = el.querySelector('.status-badge');
  if (badge) { badge.className = `status-badge ${status}`; badge.textContent = status; }
}

async function uploadFile(file) {
  const tmpId = 'tmp-' + Math.random().toString(36).slice(2);
  addQueueItem(file, tmpId);

  const form = new FormData();
  form.append('files', file);

  try {
    const res = await fetch(API + '/api/upload', { method: 'POST', body: form });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    const doc = data.documents[0];

    // Replace temp item with real id item
    const tmpEl = $(`qi-${tmpId}`);
    if (tmpEl) tmpEl.id = `qi-${doc.id}`;

    updateQueueItem(doc.id, doc.status);
    pollDocumentStatus(doc.id);
  } catch (err) {
    updateQueueItem(tmpId, 'error');
    showToast(`Upload failed: ${err.message}`, 'error');
  }
}

function pollDocumentStatus(docId) {
  if (pollingTimers[docId]) return;
  const MAX_POLLS = 60; // 2 minutes (60 × 2s)
  let pollCount = 0;
  const interval = setInterval(async () => {
    pollCount++;
    if (pollCount > MAX_POLLS) {
      clearInterval(interval);
      delete pollingTimers[docId];
      updateQueueItem(docId, 'error');
      showToast('Zpracování trvá příliš dlouho – zkus znovu', 'error');
      return;
    }
    try {
      const doc = await apiJSON(`/api/documents/${docId}`);
      updateQueueItem(docId, doc.status);
      if (doc.status === 'ready') {
        clearInterval(interval);
        delete pollingTimers[docId];
        showToast(`"${doc.original_name}" is ready`, 'success');
      } else if (doc.status === 'error') {
        clearInterval(interval);
        delete pollingTimers[docId];
        showToast(`Processing failed for "${doc.original_name}"`, 'error');
      }
    } catch {}
  }, 2000);
  pollingTimers[docId] = interval;
}

// ── Library ───────────────────────────────────────────────────────────────────
async function loadLibrary() {
  const list = $('doc-list');
  list.innerHTML = '<p class="empty-state">Loading…</p>';
  try {
    const data = await apiJSON('/api/documents');
    allDocs = data.documents;
    renderDocList(allDocs);
  } catch (err) {
    list.innerHTML = `<p class="empty-state">Error loading documents: ${escapeHtml(err.message)}</p>`;
  }
}

function renderDocList(docs) {
  const list = $('doc-list');
  if (!docs.length) {
    const q = $('doc-search') ? $('doc-search').value.trim() : '';
    if (q) {
      list.innerHTML = '<p class="empty-state">Žádné dokumenty neodpovídají hledání.</p>';
    } else {
      list.innerHTML = '<p class="empty-state">No documents yet. Upload some files to get started.</p>';
    }
    return;
  }
  list.innerHTML = '';
  docs.forEach(doc => {
    const card = document.createElement('div');
    card.className = 'doc-card' + (doc.id === selectedDocId ? ' selected' : '');
    card.dataset.id = doc.id;
    const tokens = doc.token_count ? `${doc.token_count.toLocaleString()} tokens · ` : '';
    card.innerHTML = `
      <span class="doc-icon">${fileIcon(doc.file_format)}</span>
      <div class="doc-info">
        <div class="doc-name">${escapeHtml(doc.original_name)}</div>
        <div class="doc-meta">${tokens}${formatBytes(doc.file_size)} · ${formatDate(doc.uploaded_at)}</div>
      </div>
      <span class="status-badge doc-badge ${doc.status}">${doc.status}</span>
      <button class="icon-btn delete-doc-btn" title="Smazat dokument">&#x1F5D1;</button>`;
    card.addEventListener('click', e => {
      if (e.target.closest('.delete-doc-btn')) return;
      selectDocument(doc);
    });
    const delBtn = card.querySelector('.delete-doc-btn');
    delBtn.addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm(`Smazat "${doc.original_name}"? Tuto akci nelze vrátit.`)) return;
      try {
        await apiFetch(`/api/documents/${doc.id}`, { method: 'DELETE' });
        card.remove();
        allDocs = allDocs.filter(d => d.id !== doc.id);
        if (selectedDocId === doc.id) {
          $('analysis-panel').classList.add('hidden');
          selectedDocId = null;
        }
        showToast('Dokument smazán', 'success');
      } catch (err) {
        showToast(`Chyba při mazání: ${err.message}`, 'error');
      }
    });
    list.appendChild(card);
  });
}

function selectDocument(doc) {
  if (doc.status !== 'ready') {
    showToast('Document is not ready yet', 'info');
    return;
  }
  selectedDocId = doc.id;
  document.querySelectorAll('.doc-card').forEach(c => c.classList.toggle('selected', c.dataset.id === doc.id));

  $('panel-doc-name').textContent = doc.original_name;
  $('view-library').classList.add('library-layout');
  $('analysis-panel').classList.remove('hidden');

  // Reset outputs
  ['summary-output', 'highlights-output', 'presentation-output'].forEach(id => $(`${id}`).innerHTML = '');
  $('ask-history').innerHTML = '';
}

$('refresh-btn').addEventListener('click', loadLibrary);

$('doc-search').addEventListener('input', () => {
  const q = $('doc-search').value.trim().toLowerCase();
  if (!q) {
    renderDocList(allDocs);
    return;
  }
  const filtered = allDocs.filter(d =>
    d.original_name.toLowerCase().includes(q) ||
    d.file_format.toLowerCase().includes(q)
  );
  renderDocList(filtered);
});

$('panel-close').addEventListener('click', () => {
  $('analysis-panel').classList.add('hidden');
  selectedDocId = null;
  document.querySelectorAll('.doc-card').forEach(c => c.classList.remove('selected'));
});

// ── Panel Tabs ────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => { t.classList.remove('active'); t.classList.add('hidden'); });
    btn.classList.add('active');
    const tab = $(`tab-${btn.dataset.tab}`);
    tab.classList.remove('hidden');
    tab.classList.add('active');
  });
});

// ── Summary ───────────────────────────────────────────────────────────────────
$('btn-summarize').addEventListener('click', async () => {
  if (!selectedDocId) return;
  const style = $('summary-style').value;
  const language = $('output-language') ? $('output-language').value : 'en';
  const out = $('summary-output');
  setLoading(out, 'Generating summary…');
  disableBtn('btn-summarize', true);
  try {
    const data = await apiJSON('/api/summarize', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, style, language }),
    });
    out.innerHTML = '';
    const pre = document.createElement('div');
    pre.style.whiteSpace = 'pre-wrap';
    pre.textContent = data.summary;
    out.appendChild(pre);
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
    if (data.truncated) showToast('Dokument byl zkrácen pro zpracování (příliš dlouhý pro model)', 'info');
    const docName = $('panel-doc-name').textContent.replace(/\.[^.]+$/, '');
    addExportButtons(out, data.summary, `${docName}_summary.txt`);
  } catch (err) {
    out.textContent = '';
    showToast(`Summary error: ${err.message}`, 'error');
  } finally {
    if (_loadingTimer) { clearInterval(_loadingTimer); _loadingTimer = null; }
    disableBtn('btn-summarize', false);
  }
});

// ── Highlights ────────────────────────────────────────────────────────────────
$('btn-highlights').addEventListener('click', async () => {
  if (!selectedDocId) return;
  const language = $('output-language') ? $('output-language').value : 'en';
  const out = $('highlights-output');
  setLoading(out, 'Extracting highlights…');
  disableBtn('btn-highlights', true);
  try {
    const data = await apiJSON('/api/highlights', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, language }),
    });
    renderHighlights(out, data);
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
    if (data.truncated) showToast('Dokument byl zkrácen pro zpracování (příliš dlouhý pro model)', 'info');
    const docName = $('panel-doc-name').textContent.replace(/\.[^.]+$/, '');
    const exportText = highlightsToText(data);
    addExportButtons(out, exportText, `${docName}_highlights.txt`);
  } catch (err) {
    out.innerHTML = '';
    showToast(`Highlights error: ${err.message}`, 'error');
  } finally {
    if (_loadingTimer) { clearInterval(_loadingTimer); _loadingTimer = null; }
    disableBtn('btn-highlights', false);
  }
});

function renderHighlights(container, data) {
  container.innerHTML = '';

  const sections = [
    { key: 'key_concepts',  label: 'Key Concepts' },
    { key: 'key_sentences', label: 'Key Sentences' },
    { key: 'topics',        label: 'Main Topics' },
  ];

  sections.forEach(({ key, label }) => {
    const items = data[key];
    if (!items || !items.length) return;
    const sec = document.createElement('div');
    sec.className = 'highlights-section';
    sec.innerHTML = `<h4>${label}</h4>`;
    const ul = document.createElement('ul');
    const list = Array.isArray(items) ? items : items.split(',').map(s => s.trim());
    list.forEach(item => {
      const li = document.createElement('li');
      li.textContent = item;
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    container.appendChild(sec);
  });

  if (!container.innerHTML) container.textContent = 'No highlights extracted.';
}

// ── Presentation ──────────────────────────────────────────────────────────────
$('btn-presentation').addEventListener('click', async () => {
  if (!selectedDocId) return;
  const format = $('presentation-format').value;
  const language = $('output-language') ? $('output-language').value : 'en';
  const out = $('presentation-output');

  if (format === 'pptx') {
    setLoading(out, 'Generating PPTX…');
    disableBtn('btn-presentation', true);
    try {
      const res = await apiFetch('/api/presentation', {
        method: 'POST',
        body: JSON.stringify({ document_id: selectedDocId, format: 'pptx', language }),
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const cd = res.headers.get('Content-Disposition') || '';
      const match = cd.match(/filename="([^"]+)"/);
      a.download = match ? match[1] : 'presentation.pptx';
      a.click();
      URL.revokeObjectURL(url);
      out.textContent = 'PPTX downloaded!';
      showToast('PPTX ready', 'success');
    } catch (err) {
      out.textContent = '';
      showToast(`Presentation error: ${err.message}`, 'error');
    } finally {
      if (_loadingTimer) { clearInterval(_loadingTimer); _loadingTimer = null; }
      disableBtn('btn-presentation', false);
    }
    return;
  }

  // Markdown
  setLoading(out, 'Generating outline…');
  disableBtn('btn-presentation', true);
  try {
    const data = await apiJSON('/api/presentation', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, format: 'markdown', language }),
    });
    out.textContent = data.markdown;
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
    if (data.truncated) showToast('Dokument byl zkrácen pro zpracování (příliš dlouhý pro model)', 'info');
  } catch (err) {
    out.textContent = '';
    showToast(`Presentation error: ${err.message}`, 'error');
  } finally {
    if (_loadingTimer) { clearInterval(_loadingTimer); _loadingTimer = null; }
    disableBtn('btn-presentation', false);
  }
});

// ── Ask (RAG Q&A) ─────────────────────────────────────────────────────────────
$('btn-ask').addEventListener('click', submitQuestion);
$('ask-input').addEventListener('keydown', e => { if (e.key === 'Enter') submitQuestion(); });

async function submitQuestion() {
  if (!selectedDocId) return;
  const input = $('ask-input');
  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  disableBtn('btn-ask', true);
  input.disabled = true;

  const history = $('ask-history');

  // Show question bubble
  const pair = document.createElement('div');
  pair.className = 'qa-pair';
  pair.innerHTML = `<div class="qa-question">${escapeHtml(question)}</div>
                    <div class="qa-answer"><span class="spinner-text">Thinking…</span></div>`;
  history.appendChild(pair);
  history.scrollTop = history.scrollHeight;

  try {
    const data = await apiJSON('/api/ask', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, question }),
    });
    const answerDiv = pair.querySelector('.qa-answer');
    answerDiv.textContent = data.answer;
    const meta = document.createElement('div');
    meta.className = 'qa-meta';
    meta.textContent = `${data.sources_used} context chunk(s)${data.cached ? ' · cached' : ''}`;
    pair.appendChild(meta);
  } catch (err) {
    pair.querySelector('.qa-answer').textContent = `Error: ${err.message}`;
  } finally {
    disableBtn('btn-ask', false);
    input.disabled = false;
    input.focus();
    history.scrollTop = history.scrollHeight;
  }
}

// ── Export helpers ────────────────────────────────────────────────────────────
function addExportButtons(container, text, filename) {
  const bar = document.createElement('div');
  bar.className = 'export-bar';
  const copyBtn = document.createElement('button');
  copyBtn.className = 'btn-secondary btn-sm';
  copyBtn.textContent = '📋 Kopírovat';
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(text);
    showToast('Zkopírováno do schránky', 'success', 2000);
  };
  const dlBtn = document.createElement('button');
  dlBtn.className = 'btn-secondary btn-sm';
  dlBtn.textContent = '⬇ Stáhnout';
  dlBtn.onclick = () => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };
  bar.appendChild(copyBtn);
  bar.appendChild(dlBtn);
  container.appendChild(bar);
}

function highlightsToText(data) {
  const lines = [];
  if (data.key_concepts && data.key_concepts.length) {
    lines.push('Key Concepts:');
    data.key_concepts.forEach((c, i) => lines.push(`${i + 1}. ${c}`));
    lines.push('');
  }
  if (data.key_sentences && data.key_sentences.length) {
    lines.push('Key Sentences:');
    data.key_sentences.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
    lines.push('');
  }
  if (data.topics) {
    const topicList = Array.isArray(data.topics) ? data.topics.join(', ') : data.topics;
    lines.push(`Topics: ${topicList}`);
  }
  return lines.join('\n');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setLoading(el, msg) {
  if (_loadingTimer) {
    clearInterval(_loadingTimer);
    _loadingTimer = null;
  }
  let seconds = 0;
  el.innerHTML = `
    <div class="loading-state">
      <div class="loading-spinner"></div>
      <div class="loading-message">${escapeHtml(msg)}</div>
      <div class="loading-timer" id="loading-elapsed">0s</div>
      <div class="loading-hint">Intel Mac (CPU) – může trvat 10–30s</div>
    </div>
  `;
  _loadingTimer = setInterval(() => {
    seconds++;
    const timerEl = $('loading-elapsed');
    if (timerEl) timerEl.textContent = `${seconds}s`;
  }, 1000);
}

function disableBtn(id, disabled) {
  const btn = $(id);
  if (btn) btn.disabled = disabled;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadOllamaStatus() {
  const badge = $('ollama-status');
  if (!badge) return;
  try {
    const data = await apiJSON('/api/models/status');
    if (data.ollama_running) {
      badge.className = 'status-badge online';
      badge.textContent = `Online — ${data.current_model} (${data.current_backend})`;
    } else {
      badge.className = 'status-badge offline';
      badge.textContent = 'Offline — Ollama neběží';
    }
  } catch {
    badge.className = 'status-badge offline';
    badge.textContent = 'Offline — Backend nedostupný';
  }
}

async function refreshModels() {
  const select = $('model-select');
  const grid = $('model-cards');
  if (!select || !grid) return;
  try {
    const data = await apiJSON('/api/models/available');
    const current = data.current_model;

    // Populate select
    select.innerHTML = '';
    data.available.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.name;
      opt.textContent = m.name;
      if (m.name === current) opt.selected = true;
      select.appendChild(opt);
    });

    // Render model cards
    grid.innerHTML = '';
    data.available.forEach(m => {
      const card = document.createElement('div');
      card.className = 'model-card' + (m.name === current ? ' active' : '');
      card.innerHTML = `
        <div class="model-card-name">${escapeHtml(m.name)}</div>
        <div class="model-card-meta">${m.family} · ${m.size_mb ? m.size_mb + ' MB' : 'N/A'}</div>`;
      card.addEventListener('click', () => {
        select.value = m.name;
        grid.querySelectorAll('.model-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
      });
      grid.appendChild(card);
    });
  } catch (err) {
    grid.innerHTML = `<p class="empty-state">Nepodařilo se načíst modely: ${escapeHtml(err.message)}</p>`;
  }
}

async function applyModel() {
  const select = $('model-select');
  if (!select) return;
  const model = select.value;
  if (!model) return;
  try {
    const data = await apiJSON('/api/models/switch', {
      method: 'POST',
      body: JSON.stringify({ model }),
    });
    showToast(data.message || `Model přepnut na ${model}`, 'success');
    await refreshModels();
    await loadOllamaStatus();
  } catch (err) {
    showToast(`Chyba při přepínání modelu: ${err.message}`, 'error');
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
checkHealth();
setInterval(checkHealth, 30000);
loadOllamaStatus();
refreshModels();
setInterval(loadOllamaStatus, 30000);
