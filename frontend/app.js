/**
 * app.js – Knowledge App frontend logic (v2)
 *
 * New in v2:
 *   • Provider selector: load providers from /api/providers, switch via UI
 *   • Model selector: fetch available models per provider
 *   • SSE streaming in Ask tab (token-by-token via /api/ask/stream)
 */

'use strict';

// ── Config ───────────────────────────────────────────────────────────────────
const API = '';  // empty = same origin; change to 'http://localhost:8000' for dev

// ── State ────────────────────────────────────────────────────────────────────
let selectedDocId  = null;
let pollingTimers  = {};
let activeStream   = null;   // AbortController for current SSE stream

// ── Utilities ─────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function showToast(msg, type = 'info', duration = 3500) {
  const tc = $('toast-container');
  const t  = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  tc.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

function formatBytes(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'Z');
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function fileIcon(fmt) {
  return { pdf:'📄', docx:'📝', txt:'📃', md:'📋', pptx:'📊' }[fmt] || '📁';
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function setLoading(el, msg) {
  el.innerHTML = `<span class="spinner-text">${escapeHtml(msg)}</span>`;
}

function disableBtn(id, disabled) {
  const btn = $(id);
  if (btn) btn.disabled = disabled;
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
  return (await apiFetch(path, opts)).json();
}

// ── Health check ──────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = $('health-indicator');
  try {
    const d = await apiJSON('/api/health');
    dot.className = 'health-dot ok';
    dot.title = `Backend OK — ${d.provider}/${d.model} · ${d.db_engine}`;
  } catch {
    dot.className = 'health-dot error';
    dot.title = 'Backend unreachable';
  }
}

// ── Provider selector ─────────────────────────────────────────────────────────

async function loadProviders() {
  try {
    const [listData, activeData] = await Promise.all([
      apiJSON('/api/providers'),
      apiJSON('/api/providers/active'),
    ]);

    const sel = $('provider-select');
    sel.innerHTML = '';
    listData.providers.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = p.name + (p.enabled ? '' : ' (disabled)');
      opt.selected = p.active;
      sel.appendChild(opt);
    });

    // Load models for the active provider
    await loadModels(activeData.provider, activeData.model);
  } catch (err) {
    showToast(`Could not load providers: ${err.message}`, 'error');
  }
}

async function loadModels(providerName, currentModel) {
  const sel = $('model-select');
  sel.innerHTML = '<option value="">Loading…</option>';
  try {
    const data = await apiJSON(`/api/providers/${providerName}/models`);
    sel.innerHTML = '';
    if (!data.models.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '(default)';
      sel.appendChild(opt);
      return;
    }
    data.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      opt.selected = m === currentModel;
      sel.appendChild(opt);
    });
  } catch {
    sel.innerHTML = '<option value="">(default)</option>';
  }
}

// Reload models when provider changes in the dropdown
$('provider-select').addEventListener('change', () => {
  loadModels($('provider-select').value, '');
});

// Apply button – switch provider + model
$('btn-apply-provider').addEventListener('click', async () => {
  const provider = $('provider-select').value;
  const model    = $('model-select').value || null;
  disableBtn('btn-apply-provider', true);
  try {
    const data = await apiJSON('/api/providers/switch', {
      method: 'POST',
      body: JSON.stringify({ provider, model }),
    });
    showToast(`Switched to ${data.switched_to} / ${data.model}`, 'success');
    await checkHealth();
  } catch (err) {
    showToast(`Switch failed: ${err.message}`, 'error');
  } finally {
    disableBtn('btn-apply-provider', false);
  }
});

// ── Navigation ────────────────────────────────────────────────────────────────
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('hidden', !v.id.endsWith(name)));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  if (name === 'library') loadLibrary();
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
dropZone.addEventListener('click', e => { if (e.target !== fileInput) fileInput.click(); });

function handleFiles(files) {
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
    const doc  = data.documents[0];
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
  const interval = setInterval(async () => {
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
    renderDocList(data.documents);
  } catch (err) {
    list.innerHTML = `<p class="empty-state">Error: ${escapeHtml(err.message)}</p>`;
  }
}

function renderDocList(docs) {
  const list = $('doc-list');
  if (!docs.length) {
    list.innerHTML = '<p class="empty-state">No documents yet. Upload some files to get started.</p>';
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
      <span class="status-badge doc-badge ${doc.status}">${doc.status}</span>`;
    card.addEventListener('click', () => selectDocument(doc));
    list.appendChild(card);
  });
}

function selectDocument(doc) {
  if (doc.status !== 'ready') { showToast('Document is not ready yet', 'info'); return; }
  selectedDocId = doc.id;
  document.querySelectorAll('.doc-card').forEach(c => c.classList.toggle('selected', c.dataset.id === doc.id));
  $('panel-doc-name').textContent = doc.original_name;
  $('analysis-panel').classList.remove('hidden');
  ['summary-output', 'highlights-output', 'presentation-output'].forEach(id => $(id).innerHTML = '');
  $('ask-history').innerHTML = '';
}

$('refresh-btn').addEventListener('click', loadLibrary);

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
  const out   = $('summary-output');
  setLoading(out, 'Generating summary…');
  disableBtn('btn-summarize', true);
  try {
    const data = await apiJSON('/api/summarize', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, style }),
    });
    out.textContent = data.summary;
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
  } catch (err) {
    out.textContent = '';
    showToast(`Summary error: ${err.message}`, 'error');
  } finally {
    disableBtn('btn-summarize', false);
  }
});

// ── Highlights ────────────────────────────────────────────────────────────────
$('btn-highlights').addEventListener('click', async () => {
  if (!selectedDocId) return;
  const out = $('highlights-output');
  setLoading(out, 'Extracting highlights…');
  disableBtn('btn-highlights', true);
  try {
    const data = await apiJSON('/api/highlights', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId }),
    });
    renderHighlights(out, data);
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
  } catch (err) {
    out.innerHTML = '';
    showToast(`Highlights error: ${err.message}`, 'error');
  } finally {
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
  const out    = $('presentation-output');

  if (format === 'pptx') {
    setLoading(out, 'Generating PPTX…');
    disableBtn('btn-presentation', true);
    try {
      const res  = await apiFetch('/api/presentation', {
        method: 'POST',
        body: JSON.stringify({ document_id: selectedDocId, format: 'pptx' }),
      });
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;
      const cd    = res.headers.get('Content-Disposition') || '';
      const match = cd.match(/filename="([^"]+)"/);
      a.download  = match ? match[1] : 'presentation.pptx';
      a.click();
      URL.revokeObjectURL(url);
      out.textContent = 'PPTX downloaded!';
      showToast('PPTX ready', 'success');
    } catch (err) {
      out.textContent = '';
      showToast(`Presentation error: ${err.message}`, 'error');
    } finally {
      disableBtn('btn-presentation', false);
    }
    return;
  }

  setLoading(out, 'Generating outline…');
  disableBtn('btn-presentation', true);
  try {
    const data = await apiJSON('/api/presentation', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, format: 'markdown' }),
    });
    out.textContent = data.markdown;
    if (data.cached) showToast('Loaded from cache', 'info', 2000);
  } catch (err) {
    out.textContent = '';
    showToast(`Presentation error: ${err.message}`, 'error');
  } finally {
    disableBtn('btn-presentation', false);
  }
});

// ── Ask (RAG Q&A) ─────────────────────────────────────────────────────────────
$('btn-ask').addEventListener('click', submitQuestion);
$('ask-input').addEventListener('keydown', e => { if (e.key === 'Enter') submitQuestion(); });

async function submitQuestion() {
  if (!selectedDocId) return;
  const input    = $('ask-input');
  const question = input.value.trim();
  if (!question) return;

  // Cancel any ongoing stream
  if (activeStream) { activeStream.abort(); activeStream = null; }

  input.value = '';
  disableBtn('btn-ask', true);
  input.disabled = true;

  const history = $('ask-history');
  const pair    = document.createElement('div');
  pair.className = 'qa-pair';

  const answerDiv = document.createElement('div');
  answerDiv.className = 'qa-answer';

  pair.innerHTML = `<div class="qa-question">${escapeHtml(question)}</div>`;
  pair.appendChild(answerDiv);
  history.appendChild(pair);
  history.scrollTop = history.scrollHeight;

  const useStream = $('stream-toggle').checked;

  if (useStream) {
    await streamAnswer(question, answerDiv, pair, history);
  } else {
    await blockingAnswer(question, answerDiv, pair);
  }

  disableBtn('btn-ask', false);
  input.disabled = false;
  input.focus();
  history.scrollTop = history.scrollHeight;
}

// Blocking (cached) path
async function blockingAnswer(question, answerDiv, pair) {
  answerDiv.innerHTML = '<span class="spinner-text">Thinking…</span>';
  try {
    const data = await apiJSON('/api/ask', {
      method: 'POST',
      body: JSON.stringify({ document_id: selectedDocId, question }),
    });
    answerDiv.textContent = data.answer;
    const meta = document.createElement('div');
    meta.className = 'qa-meta';
    meta.textContent = `${data.sources_used} context chunk(s)${data.cached ? ' · cached' : ''}`;
    pair.appendChild(meta);
  } catch (err) {
    answerDiv.textContent = `Error: ${err.message}`;
  }
}

// Streaming (SSE) path
async function streamAnswer(question, answerDiv, pair, history) {
  answerDiv.className = 'qa-answer stream-cursor';
  answerDiv.textContent = '';

  const controller = new AbortController();
  activeStream = controller;

  try {
    const res = await fetch(API + '/api/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: selectedDocId, question }),
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';
    let   sources = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();   // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        try {
          const msg = JSON.parse(raw);
          if (msg.type === 'meta') {
            sources = msg.sources_used;
          } else if (msg.type === 'token') {
            answerDiv.textContent += msg.text;
            history.scrollTop = history.scrollHeight;
          } else if (msg.type === 'done') {
            answerDiv.className = 'qa-answer';
            const meta = document.createElement('div');
            meta.className = 'qa-meta';
            meta.textContent = `${sources} context chunk(s) · streamed`;
            pair.appendChild(meta);
          } else if (msg.type === 'error') {
            answerDiv.className = 'qa-answer';
            answerDiv.textContent = `Error: ${msg.message}`;
          }
        } catch {}
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      answerDiv.className = 'qa-answer';
      answerDiv.textContent = `Stream error: ${err.message}`;
    }
  } finally {
    answerDiv.classList.remove('stream-cursor');
    activeStream = null;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
checkHealth();
loadProviders();
setInterval(checkHealth, 30000);
