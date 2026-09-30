/* InvoiceParser AI — frontend (vanilla JS, no build step) */
(() => {
  'use strict';

  // Same origin when served by FastAPI; override with ?api=http://host:port for a separate static server.
  const API = new URLSearchParams(location.search).get('api') || (location.protocol === 'file:' ? 'http://localhost:8000' : '');
  const POLL_MS = 700;
  const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const PREVIEWABLE_IMAGES = ['png', 'jpeg', 'jpg', 'webp', 'gif', 'bmp', 'svg'];
  const TEXT_FORMATS = ['txt', 'md', 'csv', 'tsv', 'xml', 'json', 'html', 'htm', 'eml'];

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const FIELD_SEL = 'input[data-field], select[data-field], textarea[data-field]';

  const els = {
    apiStatus: $('#apiStatus'), banner: $('#configBanner'),
    dropzone: $('#dropzone'), fileInput: $('#fileInput'), formatChips: $('#formatChips'),
    samplesBox: $('#samplesBox'), samplesList: $('#samplesList'),
    uploadCard: $('#uploadCard'), docCard: $('#docCard'),
    fileBadge: $('#fileBadge'), docName: $('#docName'), docMeta: $('#docMeta'),
    stepper: $('#stepper'), errorBox: $('#errorBox'),
    previewPanel: $('#previewPanel'), textPanel: $('#textPanel'), jsonPanel: $('#jsonPanel'),
    form: $('#invoiceForm'), formSubtitle: $('#formSubtitle'),
    scoreRing: $('#scoreRing'), scoreText: $('#scoreText'),
    checksBox: $('#checksBox'), checksList: $('#checksList'),
    itemsBody: $('#itemsBody'), itemsCount: $('#itemsCount'), itemTpl: $('#itemRowTpl'),
    drawer: $('#historyDrawer'), backdrop: $('#drawerBackdrop'), historyList: $('#historyList'),
    toasts: $('#toasts'),
  };

  const state = {
    file: null,
    objectUrl: null,
    filename: null,
    runId: 0,          // guards against stale polling when a new file is dropped
    lastResult: null,
    health: null,
    accept: [],
  };

  // ------------------------------------------------------------------ utils

  async function api(path, options = {}) {
    const res = await fetch(API + path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try { const body = await res.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch (_) {}
      throw new Error(detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    const type = res.headers.get('content-type') || '';
    return type.includes('application/json') ? res.json() : res.blob();
  }

  function toast(message, kind = 'ok') {
    const icon = kind === 'ok' ? 'i-check' : kind === 'bad' ? 'i-x-circle' : 'i-alert';
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = `<svg><use href="#${icon}"/></svg><span></span>`;
    el.querySelector('span').textContent = message;
    els.toasts.appendChild(el);
    setTimeout(() => { el.classList.add('out'); el.addEventListener('animationend', () => el.remove()); }, 3200);
  }

  function extOf(name) {
    const m = /\.([a-z0-9]+)$/i.exec(name || '');
    return m ? m[1].toLowerCase() : '';
  }

  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  function formatMoney(value, currency) {
    if (value == null || value === '') return '—';
    try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD' }).format(value); }
    catch (_) { return `${currency || ''} ${Number(value).toFixed(2)}`.trim(); }
  }

  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: filename });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function baseName() {
    return (state.filename || 'document').replace(/\.[^.]+$/, '').replace(/[^\w-]+/g, '_');
  }

  // ------------------------------------------------------------------ theme

  function currentTheme() {
    return document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  function paintThemeIcon() {
    $('#themeBtn use').setAttribute('href', currentTheme() === 'dark' ? '#i-sun' : '#i-moon');
  }
  $('#themeBtn').addEventListener('click', () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (_) {}
    paintThemeIcon();
  });
  paintThemeIcon();

  // ------------------------------------------------------------------ boot

  async function boot() {
    try {
      const health = await api('/api/health');
      state.health = health;
      els.apiStatus.className = `status-pill ${health.llm_configured ? 'ok' : 'warn'}`;
      $('.label', els.apiStatus).textContent = health.llm_configured ? health.model : 'API key missing';
      els.banner.hidden = health.llm_configured;
    } catch (_) {
      els.apiStatus.className = 'status-pill bad';
      $('.label', els.apiStatus).textContent = 'API offline';
    }

    try {
      const { formats, max_file_size_mb } = await api('/api/formats');
      const exts = formats.flatMap((f) => f.extensions);
      state.accept = exts;
      els.fileInput.accept = exts.join(',');
      const shown = ['pdf', 'jpg', 'png', 'webp', 'heic', 'tiff', 'docx', 'xlsx', 'csv', 'xml', 'json', 'html', 'txt', 'eml'];
      els.formatChips.innerHTML = shown.map((e) => `<span class="chip">${e}</span>`).join('') +
        `<span class="chip" title="Maximum file size">≤ ${max_file_size_mb} MB</span>`;
    } catch (_) { /* offline: keep defaults */ }

    try {
      const samples = await api('/api/samples');
      if (samples.length) {
        els.samplesBox.hidden = false;
        els.samplesList.innerHTML = '';
        for (const s of samples) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'sample';
          btn.innerHTML = `<span class="ext"></span><span class="name"></span>`;
          $('.ext', btn).textContent = extOf(s.name);
          $('.name', btn).textContent = s.name.replace(/\.[^.]+$/, '').replace(/-/g, ' ');
          btn.addEventListener('click', () => loadSample(s));
          els.samplesList.appendChild(btn);
        }
      }
    } catch (_) {}

    renderItems([]);
  }

  async function loadSample(sample) {
    try {
      const blob = await api(sample.url.startsWith('/') ? sample.url : `/${sample.url}`);
      handleFile(new File([blob], sample.name, { type: blob.type }));
    } catch (e) { toast(`Could not load sample: ${e.message}`, 'bad'); }
  }

  // ------------------------------------------------------------------ upload

  const dz = els.dropzone;
  dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); els.fileInput.click(); } });
  els.fileInput.addEventListener('change', () => { if (els.fileInput.files[0]) handleFile(els.fileInput.files[0]); els.fileInput.value = ''; });
  ['dragenter', 'dragover'].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((ev) => document.addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === 'dragleave' && e.relatedTarget) return;
    dz.classList.remove('dragover');
  }));
  document.addEventListener('drop', (e) => { const f = e.dataTransfer?.files?.[0]; if (f) handleFile(f); });
  document.addEventListener('paste', (e) => {
    if (e.target.closest('input, textarea')) return;
    const item = [...(e.clipboardData?.items || [])].find((i) => i.kind === 'file');
    const file = item?.getAsFile();
    if (file) {
      const name = file.name && file.name !== 'image.png' ? file.name : `pasted-${Date.now()}.${(file.type.split('/')[1] || 'png')}`;
      handleFile(new File([file], name, { type: file.type }));
    }
  });
  $('#newFileBtn').addEventListener('click', () => els.fileInput.click());

  async function handleFile(file) {
    const runId = ++state.runId;
    state.file = file;
    state.filename = file.name;
    state.lastResult = null;

    els.uploadCard.hidden = true;
    els.docCard.hidden = false;
    els.errorBox.hidden = true;
    els.fileBadge.textContent = extOf(file.name) || 'file';
    els.docName.textContent = file.name;
    els.docName.title = file.name;
    setMeta([formatBytes(file.size), 'uploading…']);
    els.textPanel.textContent = 'Text will appear here after processing.';
    els.jsonPanel.textContent = '{}';
    renderPreview(file);
    selectTab('preview');
    clearForm({ keepFile: true });
    els.formSubtitle.textContent = 'Reading your document…';

    try {
      const body = new FormData();
      body.append('file', file);
      let job = await api('/api/extract', { method: 'POST', body });
      renderStepper(job);
      while (job.status === 'queued' || job.status === 'processing') {
        await sleep(POLL_MS);
        if (runId !== state.runId) return;
        job = await api(`/api/jobs/${job.id}`);
        renderStepper(job);
      }
      if (runId !== state.runId) return;
      if (job.status === 'failed') throw new Error(job.error || 'Extraction failed');
      await showResult(job.result, runId);
    } catch (err) {
      if (runId !== state.runId) return;
      failSteps();
      els.errorBox.hidden = false;
      els.errorBox.innerHTML = '<svg><use href="#i-alert"/></svg><span></span>';
      $('span', els.errorBox).textContent = err.message;
      els.formSubtitle.textContent = 'Extraction failed — you can still fill the form manually.';
      setMeta([formatBytes(file.size), 'failed']);
      toast(err.message, 'bad');
    }
  }

  function setMeta(parts) {
    els.docMeta.innerHTML = '';
    parts.filter(Boolean).forEach((p) => {
      const span = document.createElement('span');
      if (typeof p === 'object') { span.className = 'tag'; span.textContent = p.tag; } else span.textContent = p;
      els.docMeta.appendChild(span);
    });
  }

  function renderPreview(file) {
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = URL.createObjectURL(file);
    const ext = extOf(file.name);
    const panel = els.previewPanel;
    panel.innerHTML = '';
    if (ext === 'pdf') {
      const iframe = document.createElement('iframe');
      iframe.src = state.objectUrl;
      iframe.title = file.name;
      panel.appendChild(iframe);
    } else if (PREVIEWABLE_IMAGES.includes(ext) || /^image\/(png|jpe?g|webp|gif|bmp)$/.test(file.type)) {
      const img = document.createElement('img');
      img.src = state.objectUrl;
      img.alt = file.name;
      panel.appendChild(img);
    } else if (TEXT_FORMATS.includes(ext)) {
      const pre = document.createElement('pre');
      pre.className = 'code preview-text';
      file.slice(0, 200_000).text().then((t) => { pre.textContent = t; });
      panel.appendChild(pre);
    } else {
      panel.innerHTML = `<div class="preview-empty"><svg><use href="#i-file"/></svg>
        <div>No inline preview for <b>.${ext || 'file'}</b> files.</div>
        <div>Check the <b>Extracted text</b> tab once processing finishes.</div></div>`;
    }
  }

  // ------------------------------------------------------------------ progress

  function renderStepper(job) {
    const activeIndex = job.steps.findIndex((s) => s.id === job.step);
    els.stepper.innerHTML = '';
    job.steps.forEach((s, i) => {
      const li = document.createElement('li');
      let cls = 'step';
      if (job.status === 'completed' || (activeIndex > -1 && i < activeIndex)) cls += ' done';
      else if (i === activeIndex && job.status === 'processing') cls += ' active';
      li.className = cls;
      li.innerHTML = '<div class="bar"></div><span></span>';
      $('span', li).textContent = s.label;
      els.stepper.appendChild(li);
    });
    const current = job.steps[activeIndex];
    if (job.status !== 'completed') setMeta([formatBytes(state.file.size), current ? `${current.label}…` : 'queued']);
  }

  function failSteps() {
    const active = $('.step.active', els.stepper) || $('.step:not(.done)', els.stepper);
    if (active) { active.classList.remove('active'); active.classList.add('failed'); }
  }

  // ------------------------------------------------------------------ result

  async function showResult(result, runId) {
    state.lastResult = result;
    const doc = result.document;
    const seconds = Object.values(result.timings || {}).reduce((a, b) => a + b, 0);
    setMeta([
      formatBytes(state.file.size),
      doc.pages > 1 ? `${doc.pages} pages` : null,
      { tag: doc.method },
      `${seconds.toFixed(1)} s`,
      result.usage?.total ? `${result.usage.total.toLocaleString()} tokens` : null,
    ]);
    els.textPanel.textContent = doc.text_preview || (doc.images_sent ? `The document was read visually (${doc.images_sent} image${doc.images_sent > 1 ? 's' : ''} sent to the model).` : '—');
    els.jsonPanel.textContent = JSON.stringify(result.data, null, 2);
    els.formSubtitle.textContent = `Filled by AI from ${doc.filename} — review and edit anything.`;

    await fillForm(result.data, { animate: !REDUCED_MOTION, runId });
    if (runId !== state.runId) return;
    renderScore(result.completeness);
    renderChecks(result.checks);
    const warnings = result.checks.filter((c) => c.status !== 'pass').length;
    toast(warnings ? `Extracted with ${warnings} warning${warnings > 1 ? 's' : ''} to review` : 'Extraction complete', warnings ? 'warn' : 'ok');
  }

  function renderScore(value) {
    const pct = Math.round((value || 0) * 100);
    els.scoreRing.hidden = false;
    els.scoreText.textContent = `${pct}%`;
    const circle = $('.value', els.scoreRing);
    const len = 2 * Math.PI * 15.5;
    circle.style.strokeDasharray = len;
    circle.style.strokeDashoffset = len;
    requestAnimationFrame(() => { circle.style.strokeDashoffset = len * (1 - pct / 100); });
    circle.style.stroke = pct >= 75 ? 'var(--ok)' : pct >= 50 ? 'var(--warn)' : 'var(--bad)';
  }

  function renderChecks(checks) {
    els.checksList.innerHTML = '';
    $$('.flagged').forEach((el) => el.classList.remove('flagged'));
    if (!checks?.length) { els.checksBox.hidden = true; return; }
    els.checksBox.hidden = false;
    const icons = { pass: 'i-check', warn: 'i-alert', fail: 'i-x-circle' };
    checks.forEach((c, i) => {
      const li = document.createElement('li');
      li.className = `check ${c.status}`;
      li.style.animationDelay = `${i * 60}ms`;
      li.innerHTML = `<svg><use href="#${icons[c.status]}"/></svg><div><b></b> <span class="detail"></span></div>`;
      $('b', li).textContent = c.label;
      $('.detail', li).textContent = c.detail;
      const target = c.field && fieldElement(c.field);
      if (target) {
        li.dataset.target = c.field;
        if (c.status !== 'pass') target.classList.add('flagged');
        li.addEventListener('click', () => {
          target.scrollIntoView({ behavior: REDUCED_MOTION ? 'auto' : 'smooth', block: 'center' });
          target.classList.remove('flash'); void target.offsetWidth; target.classList.add('flash');
          if (target.focus) target.focus({ preventScroll: true });
        });
      }
      els.checksList.appendChild(li);
    });
  }

  function fieldElement(path) {
    if (path === 'items') return $('.table-wrap');
    if (path === 'withholding') return $('[data-field="withholding.amount"]');
    return $(`[data-field="${path}"]`);
  }

  // ------------------------------------------------------------------ form <-> data

  const getPath = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);

  async function typeInto(el, value, runId) {
    el.classList.add('ai-typing');
    el.scrollIntoView?.({ block: 'nearest' });
    const text = String(value);
    if (el.tagName === 'SELECT' || el.type === 'date' || el.type === 'number') {
      el.value = text;
      await sleep(70);
    } else {
      const step = Math.max(1, Math.ceil(text.length / 14)); // ~14 frames per field, whatever its length
      for (let i = step; i < text.length + step; i += step) {
        if (runId !== state.runId) return;
        el.value = text.slice(0, i);
        await sleep(12);
      }
    }
    el.classList.remove('ai-typing');
    el.classList.add('ai-filled');
  }

  async function fillForm(data, { animate = false, runId = state.runId } = {}) {
    const fields = $$(FIELD_SEL, els.form);
    for (const el of fields) {
      const value = getPath(data, el.dataset.field);
      if (value == null || value === '') continue;
      if (runId !== state.runId) return;
      const shown = displayValue(el, value);
      if (animate) await typeInto(el, shown, runId);
      else { el.value = shown; el.classList.add('ai-filled'); }
    }
    await renderItems(data.items || [], { animate, runId, fromAI: true });
  }

  // Money inputs (step 0.01) always show two decimals: 4500 -> 4500.00
  function displayValue(el, value) {
    if (el.type === 'number' && el.step === '0.01' && Number.isFinite(Number(value))) return Number(value).toFixed(2);
    return value;
  }

  function num(v) {
    if (v === '' || v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function collectForm() {
    const data = { issuer: {}, customer: {}, withholding: {}, items: [] };
    for (const el of $$(FIELD_SEL, els.form)) {
      const path = el.dataset.field.split('.');
      let value = el.value.trim();
      value = el.type === 'number' ? num(value) : (value || null);
      if (value != null && el.classList.contains('upper')) value = value.toUpperCase();
      if (path.length === 1) data[path[0]] = value;
      else data[path[0]][path[1]] = value;
    }
    if (data.withholding.percentage == null && data.withholding.amount == null) data.withholding = null;
    data.items = $$('tr', els.itemsBody)
      .filter((tr) => !tr.classList.contains('items-empty'))
      .map((tr) => {
        const get = (k) => $(`[data-item="${k}"]`, tr).value.trim();
        return { description: get('description') || null, quantity: num(get('quantity')), unit_price: num(get('unit_price')), amount: num(get('amount')) };
      })
      .filter((it) => it.description || it.amount != null);
    return data;
  }

  function clearForm({ keepFile = false } = {}) {
    state.runId += keepFile ? 0 : 1;
    els.form.reset();
    $$('.ai-filled, .flagged, .ai-typing').forEach((el) => el.classList.remove('ai-filled', 'flagged', 'ai-typing'));
    renderItems([]);
    els.checksBox.hidden = true;
    els.scoreRing.hidden = true;
    if (!keepFile) {
      els.formSubtitle.textContent = 'Upload a document and watch the form fill itself.';
      els.docCard.hidden = true;
      els.uploadCard.hidden = false;
      state.filename = null;
      state.lastResult = null;
    }
  }

  // ------------------------------------------------------------------ items table

  async function renderItems(items, { animate = false, runId = state.runId, fromAI = false } = {}) {
    els.itemsBody.innerHTML = '';
    if (!items.length) {
      els.itemsBody.innerHTML = '<tr class="items-empty"><td colspan="5">No line items yet</td></tr>';
      updateItemsCount();
      return;
    }
    for (const item of items) {
      if (runId !== state.runId) return;
      addItemRow(item, { fromAI, animate });
      if (animate) await sleep(90);
    }
  }

  function addItemRow(item = {}, { fromAI = false, animate = false } = {}) {
    $('.items-empty', els.itemsBody)?.remove();
    const tr = els.itemTpl.content.firstElementChild.cloneNode(true);
    for (const input of $$('[data-item]', tr)) {
      const v = item[input.dataset.item];
      if (v != null) { input.value = displayValue(input, v); if (fromAI) input.classList.add('ai-filled'); }
    }
    if (animate) tr.classList.add('row-in');
    els.itemsBody.appendChild(tr);
    flagRow(tr);
    updateItemsCount();
    return tr;
  }

  function flagRow(tr) {
    const q = num($('[data-item="quantity"]', tr).value);
    const p = num($('[data-item="unit_price"]', tr).value);
    const a = num($('[data-item="amount"]', tr).value);
    tr.classList.toggle('row-bad', q != null && p != null && a != null && Math.abs(q * p - a) > Math.max(0.05, Math.abs(a) * 0.01));
  }

  function updateItemsCount() {
    els.itemsCount.textContent = $$('tr:not(.items-empty)', els.itemsBody).length;
  }

  els.itemsBody.addEventListener('input', (e) => {
    const tr = e.target.closest('tr');
    e.target.classList.remove('ai-filled');
    const key = e.target.dataset.item;
    if (key === 'quantity' || key === 'unit_price') {
      const q = num($('[data-item="quantity"]', tr).value);
      const p = num($('[data-item="unit_price"]', tr).value);
      if (q != null && p != null) $('[data-item="amount"]', tr).value = (q * p).toFixed(2);
    }
    flagRow(tr);
  });
  els.itemsBody.addEventListener('click', (e) => {
    const btn = e.target.closest('.remove-item');
    if (!btn) return;
    btn.closest('tr').remove();
    if (!$('tr', els.itemsBody)) renderItems([]);
    updateItemsCount();
  });
  $('#addItemBtn').addEventListener('click', () => $('[data-item="description"]', addItemRow()).focus());

  els.form.addEventListener('input', (e) => {
    if (e.target.matches(FIELD_SEL)) e.target.classList.remove('ai-filled', 'flagged');
  });

  $('#recalcBtn').addEventListener('click', () => {
    const data = collectForm();
    const set = (field, v) => { const el = $(`[data-field="${field}"]`); el.value = v.toFixed(2); el.classList.remove('ai-filled', 'flagged'); };
    const lines = data.items.reduce((s, it) => s + (it.amount || 0), 0);
    const discount = data.discount || 0;
    const rate = data.tax_rate ?? 18;
    if (data.items.length) set('subtotal', lines);
    const base = (data.items.length ? lines : data.subtotal || 0) - discount;
    const tax = base * rate / 100;
    set('tax', tax);
    set('total', base + tax);
    if (data.tax_rate == null) $('[data-field="tax_rate"]').value = rate;
    if (data.withholding?.percentage) set('withholding.amount', (base + tax) * data.withholding.percentage / 100);
    toast(`Recalculated with ${rate}% tax`, 'ok');
  });

  // ------------------------------------------------------------------ actions

  $('#resetBtn').addEventListener('click', () => clearForm());

  $('#jsonBtn').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(collectForm(), null, 2)], { type: 'application/json' });
    download(blob, `${baseName()}.json`);
  });

  $('#copyBtn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(collectForm(), null, 2)); toast('JSON copied to clipboard'); }
    catch (_) { toast('Clipboard not available', 'bad'); }
  });

  $('#excelBtn').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const blob = await api('/api/export/xlsx', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: collectForm(), filename: state.filename }),
      });
      download(blob, `${baseName()}.xlsx`);
    } catch (err) { toast(`Excel export failed: ${err.message}`, 'bad'); }
    finally { btn.disabled = false; }
  });

  els.form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#saveBtn');
    btn.disabled = true;
    try {
      const { id } = await api('/api/documents', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: collectForm(), filename: state.filename }),
      });
      toast(`Saved as document #${id}`);
    } catch (err) { toast(`Save failed: ${err.message}`, 'bad'); }
    finally { btn.disabled = false; }
  });

  // ------------------------------------------------------------------ history drawer

  function openDrawer() {
    els.backdrop.hidden = false;
    els.drawer.classList.add('open');
    els.drawer.setAttribute('aria-hidden', 'false');
    loadHistory();
  }
  function closeDrawer() {
    els.backdrop.hidden = true;
    els.drawer.classList.remove('open');
    els.drawer.setAttribute('aria-hidden', 'true');
  }
  $('#historyBtn').addEventListener('click', openDrawer);
  $('#closeDrawerBtn').addEventListener('click', closeDrawer);
  els.backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

  async function loadHistory() {
    els.historyList.innerHTML = '<li class="history-empty">Loading…</li>';
    try {
      const { items } = await api('/api/documents?limit=100');
      if (!items.length) { els.historyList.innerHTML = '<li class="history-empty">Nothing saved yet.<br>Extract a document and press <b>Save</b>.</li>'; return; }
      els.historyList.innerHTML = '';
      for (const doc of items) {
        const li = document.createElement('li');
        li.className = 'history-item';
        li.innerHTML = `<div class="main"><div class="title"></div><div class="sub"></div></div>
          <div class="amount"></div>
          <button class="icon-btn icon-btn-sm" title="Delete" aria-label="Delete"><svg><use href="#i-trash"/></svg></button>`;
        $('.title', li).textContent = doc.issuer_name || doc.customer_name || doc.filename || `Document #${doc.id}`;
        $('.sub', li).textContent = [doc.document_number, doc.issue_date, doc.filename].filter(Boolean).join(' · ');
        $('.amount', li).textContent = formatMoney(doc.total, doc.currency);
        li.addEventListener('click', async (e) => {
          if (e.target.closest('button')) return;
          const full = await api(`/api/documents/${doc.id}`);
          closeDrawer();
          clearForm();
          state.filename = full.filename;
          els.formSubtitle.textContent = `Loaded saved document #${doc.id}${full.filename ? ` (${full.filename})` : ''}.`;
          await fillForm(full.data);
        });
        $('button', li).addEventListener('click', async () => {
          await api(`/api/documents/${doc.id}`, { method: 'DELETE' });
          li.remove();
          if (!$('.history-item', els.historyList)) loadHistory();
        });
        els.historyList.appendChild(li);
      }
    } catch (err) {
      els.historyList.innerHTML = '';
      const li = document.createElement('li');
      li.className = 'history-empty';
      li.textContent = `Could not load history: ${err.message}`;
      els.historyList.appendChild(li);
    }
  }

  // ------------------------------------------------------------------ tabs

  function selectTab(name) {
    $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.dataset.panel === name));
  }
  $$('.tab').forEach((t) => t.addEventListener('click', () => selectTab(t.dataset.tab)));

  boot();
})();
