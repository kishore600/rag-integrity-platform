/* RAG Integrity dashboard. No framework, no innerHTML: every value is inserted as text. */
(() => {
'use strict';

// ---------------------------------------------------------------- DOM helpers
const $ = (s, r = document) => r.querySelector(s);
function append(el, ...kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'value') el.value = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
const NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  append(el, kids);
  return el;
}
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

// ---------------------------------------------------------------- formatting
const num = (n) => (n == null ? '-' : Number(n).toLocaleString());
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '-');
function ago(iso) {
  if (!iso) return '-';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' h ago';
  return Math.floor(s / 86400) + ' d ago';
}
const short = (s) => (s ? (s.length > 14 ? s.slice(0, 12) + '…' : s) : '-');
const money = (n) => (n == null ? '-' : '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: n < 1 ? 4 : 2 }));
const SEV = ['critical', 'high', 'medium', 'low', 'info'];
const TYPES = {
  missing_embedding: 'Missing embeddings', partial_index: 'Partial index', stale_embedding: 'Stale embeddings',
  superseded_active: 'Superseded vectors active', orphan_vector: 'Orphan vectors', duplicate_chunk: 'Duplicate chunks',
  metadata_inconsistent: 'Metadata mismatch', pipeline_drift: 'Pipeline drift', empty_embedding: 'Empty embeddings',
  tenant_mismatch: 'Tenant mismatch', manifest_orphan: 'Orphan manifest rows',
};
const ACTIONS = {
  reindex_full: 'Re-process the whole document (parse, chunk, embed, upsert).',
  reindex_chunks: 'Re-embed only the missing chunks.',
  cleanup_vectors: 'Remove the superseded vectors, only after replacements are verified.',
  fix_metadata: 'Correct the manifest / payload metadata. No re-embedding needed.',
  investigate: 'Needs a human to look at it.',
};
const label = (t) => TYPES[t] || t;
const pill = (txt, cls) => h('span', { class: 'pill ' + (cls || txt) }, String(txt).replace(/_/g, ' '));

// ---------------------------------------------------------------- state, api
let apiKey = '';
try { apiKey = sessionStorage.getItem('ragi_key') || ''; } catch (_) { /* storage may be blocked */ }
const state = { ov: null, polling: false, issueFilters: { status: 'open', severity: '', type: '', q: '', offset: 0 },
  docFilters: { status: '', q: '', offset: 0 } };

async function api(path, opts = {}, retried = false) {
  const headers = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (apiKey) headers['X-API-Key'] = apiKey;
  const res = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401 && !retried) { await askKey(); return api(path, opts, true); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (_) { /* not json */ }
    throw new Error(detail);
  }
  return (res.headers.get('content-type') || '').includes('json') ? res.json() : res.text();
}
const post = (path, body) => api(path, { method: 'POST', body: body === undefined ? {} : body });

function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3500);
}

// ---------------------------------------------------------------- drawer
let lastFocus = null;
function openDrawer(title, ...content) {
  lastFocus = document.activeElement;
  $('#drawer-title').textContent = title;
  append(clear($('#drawer-body')), content);
  $('#drawer').hidden = false; $('#scrim').hidden = false;
  $('#drawer-close').focus();
}
function closeDrawer() {
  $('#drawer').hidden = true; $('#scrim').hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
function askKey() {
  return new Promise((resolve, reject) => {
    const input = h('input', { type: 'password', autocomplete: 'off', 'aria-label': 'API key' });
    const form = h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault(); apiKey = input.value.trim();
      try { sessionStorage.setItem('ragi_key', apiKey); } catch (_) { /* ignore */ }
      closeDrawer(); resolve();
    } }, h('p', {}, 'This server requires an API key (RAGI_API_KEY). It is kept in this tab only.'), input,
      h('button', { class: 'btn primary', type: 'submit' }, 'Use key'));
    openDrawer('API key required', form); input.focus();
    $('#drawer-close').onclick = () => { closeDrawer(); reject(new Error('API key required')); };
  });
}

// ---------------------------------------------------------------- small widgets
function kpi(value, lbl, cls) { return h('div', { class: 'card kpi ' + (cls || '') }, h('div', { class: 'value' }, value), h('div', { class: 'label' }, lbl)); }
function docCell(tenant, doc) { return h('div', { class: 'doc' }, h('span', { class: 'd mono' }, doc), h('span', { class: 't' }, tenant)); }
function empty(msg) { return h('div', { class: 'empty' }, msg); }
function bars(rows, max, colorFn) {
  const top = max || Math.max(1, ...rows.map((r) => r.value));
  return h('div', { class: 'bars' }, rows.map((r) => {
    const fill = h('div', { class: 'fill ' + (colorFn ? colorFn(r) : '') });
    fill.style.width = Math.max(2, (100 * r.value) / top) + '%';
    return h('div', { class: 'bar' }, h('span', {}, r.label), h('div', { class: 'track' }, fill), h('span', { class: 'num' }, num(r.value)));
  }));
}
function meter(value, max) {
  const fill = h('div', { class: 'fill' });
  fill.style.width = Math.max(2, Math.min(100, (100 * value) / (max || 1))) + '%';
  return h('div', { class: 'track' }, fill);
}
function ring(score) {
  const r = 52, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, score ?? 0));
  const color = score == null ? 'var(--muted)' : pct >= 95 ? 'var(--ok)' : pct >= 80 ? 'var(--med)' : 'var(--crit)';
  const arc = svg('circle', { cx: 65, cy: 65, r, fill: 'none', 'stroke-width': 12, 'stroke-linecap': 'round', transform: 'rotate(-90 65 65)',
    'stroke-dasharray': `${(c * pct) / 100} ${c}` });
  arc.style.stroke = color;
  const track = svg('circle', { cx: 65, cy: 65, r, fill: 'none', 'stroke-width': 12 }); track.style.stroke = 'var(--surface-2)';
  const t1 = svg('text', { x: 65, y: 70, 'text-anchor': 'middle', 'font-size': 28, 'font-weight': 700 }, score == null ? '-' : pct.toFixed(pct % 1 ? 1 : 0) + '%');
  return svg('svg', { class: 'ring', width: 130, height: 130, viewBox: '0 0 130 130', role: 'img', 'aria-label': `Health score ${score ?? 'unknown'} percent` }, track, arc, t1);
}
function sparkline(trend) {
  const pts = trend.filter((t) => t.health_score != null);
  if (pts.length < 2) return h('p', { class: 'muted small' }, 'Run more audits to see the trend.');
  const W = 300, H = 70, min = Math.max(0, Math.min(...pts.map((p) => p.health_score)) - 5), span = 100 - min || 1;
  const xy = pts.map((p, i) => `${(i / (pts.length - 1)) * W},${H - 4 - ((p.health_score - min) / span) * (H - 8)}`).join(' ');
  const line = svg('polyline', { points: xy, fill: 'none', 'stroke-width': 2.5, 'stroke-linejoin': 'round' }); line.style.stroke = 'var(--accent)';
  return svg('svg', { class: 'spark', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Health score trend' }, line);
}
function dl(obj, skip = []) {
  const d = h('dl', { class: 'kv' });
  for (const [k, v] of Object.entries(obj)) {
    if (skip.includes(k) || v == null || v === '' || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length)) continue;
    d.append(h('dt', {}, k.replace(/_/g, ' ')), h('dd', {}, Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v)));
  }
  return d;
}
const jsonBlock = (o, summary) => h('details', {}, h('summary', {}, summary || 'Raw evidence'), h('pre', {}, JSON.stringify(o, null, 2)));

// ---------------------------------------------------------------- views
const VIEWS = [
  { id: 'overview', label: 'Overview', sub: 'Is the vector index consistent with the latest source data?' },
  { id: 'issues', label: 'Issues', sub: 'Everything the reconciliation engine found, with evidence.' },
  { id: 'documents', label: 'Documents', sub: 'Document-level integrity: which documents are inconsistent.' },
  { id: 'repairs', label: 'Repairs', sub: 'Plan, hand to your worker, verify, then clean up safely.' },
  { id: 'impact', label: 'Impact & cost', sub: 'Safe reindex recommendations and blast-radius analysis.' },
  { id: 'history', label: 'Audit history', sub: 'Every audit, issue change and repair step.' },
  { id: 'connections', label: 'Connections', sub: 'Read-only connectors to your infrastructure.' },
];

async function viewOverview(root) {
  const ov = state.ov;
  const d = ov.documents, iss = ov.issues, run = ov.latest_full_run;
  if (!run) { append(root, h('div', { class: 'card' }, empty('No audit has completed yet. Run your first audit.'))); return; }
  const broken = (d.by_status.broken || 0) + (d.by_status.orphaned || 0);
  append(root, h('div', { class: 'stack' },
    h('div', { class: 'grid g3' },
      h('div', { class: 'card span2 hero' }, ring(d.health_score),
        h('div', { class: 'stack' },
          h('div', {}, h('h2', {}, 'Index health'),
            h('p', { class: 'muted' }, `${num(d.total - broken - (d.by_status.degraded || 0))} of ${num(d.total)} documents match the latest source exactly.`)),
          h('p', { class: 'small muted' }, `Last full audit ${ago(run.finished_at)} · ${num(run.stats.index_points)} vectors · ${run.stats.duration_seconds}s · trigger: ${run.trigger}`),
          h('div', { class: 'row' }, h('button', { class: 'btn primary sm', onclick: () => go('issues') }, 'Review issues'),
            h('button', { class: 'btn sm', onclick: () => go('repairs') }, 'Plan a repair')))),
      h('div', { class: 'card' }, h('h2', {}, 'Health trend'), sparkline(ov.trend), h('p', { class: 'small muted' }, `${ov.trend.length} full audit(s) recorded`))),
    h('div', { class: 'grid g4' },
      kpi(num(iss.open), 'open issues'), kpi(num(iss.by_severity.critical), 'critical', iss.by_severity.critical ? 'crit' : ''),
      kpi(num(broken), 'documents broken or orphaned'), kpi(num(iss.resolved), 'issues resolved so far')),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card' }, h('h2', {}, 'Open issues by severity'),
        iss.open ? bars(SEV.map((s) => ({ label: s[0].toUpperCase() + s.slice(1), value: iss.by_severity[s] || 0, sev: s })), 0, (r) => r.sev) : empty('Nothing open.')),
      h('div', { class: 'card' }, h('h2', {}, 'Open issues by type'),
        iss.open ? bars(Object.entries(iss.by_type).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ label: label(t), value: n }))) : empty('Nothing open.'))),
    h('div', { class: 'card' }, h('h2', {}, 'Tenants'),
      h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ['Tenant', 'Documents', 'Healthy', 'Health'].map((x) => h('th', {}, x)))),
        h('tbody', {}, d.tenants.map((t) => h('tr', { class: 'click', onclick: () => { state.docFilters = { status: '', q: '', offset: 0, tenant: t.tenant_id }; go('documents'); } },
          h('td', {}, h('strong', {}, t.tenant_id)), h('td', {}, num(t.documents)), h('td', {}, num(t.healthy)),
          h('td', { style: { minWidth: '160px' } }, bars([{ label: t.health_score + '%', value: t.health_score }], 100, () => (t.health_score >= 95 ? '' : t.health_score >= 80 ? 'medium' : 'critical')))))))))));
}

async function viewIssues(root) {
  const f = state.issueFilters;
  const table = h('div', { class: 'card' });
  const sel = (key, opts, ph) => h('select', { 'aria-label': ph, onchange: (e) => { f[key] = e.target.value; f.offset = 0; refresh(); } },
    h('option', { value: '' }, ph), opts.map(([v, l]) => h('option', { value: v, selected: f[key] === v }, l)));
  const search = h('input', { type: 'search', placeholder: 'Search document or title', 'aria-label': 'Search', value: f.q });
  search.addEventListener('keydown', (e) => { if (e.key === 'Enter') { f.q = search.value; f.offset = 0; refresh(); } });
  append(root, h('div', { class: 'filters' },
    h('select', { 'aria-label': 'Status', onchange: (e) => { f.status = e.target.value; f.offset = 0; refresh(); } },
      ['open', 'resolved', 'ignored', 'all'].map((s) => h('option', { value: s, selected: f.status === s }, s[0].toUpperCase() + s.slice(1)))),
    sel('severity', SEV.map((s) => [s, s]), 'All severities'), sel('type', Object.entries(TYPES), 'All types'), search), table);
  async function refresh() {
    const p = new URLSearchParams({ status: f.status, limit: 50, offset: f.offset });
    for (const k of ['severity', 'type', 'q']) if (f[k]) p.set(k, f[k]);
    const data = await api('/api/issues?' + p);
    clear(table);
    if (!data.items.length) { table.append(empty(f.status === 'open' ? 'No open issues. The index agrees with the source.' : 'No issues match.')); return; }
    table.append(h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Severity', 'Issue', 'Document', 'Detail', 'Last seen'].map((x) => h('th', {}, x)))),
      h('tbody', {}, data.items.map((i) => h('tr', { class: 'click', tabindex: 0, onclick: () => openIssue(i.id), onkeydown: (e) => { if (e.key === 'Enter') openIssue(i.id); } },
        h('td', {}, pill(i.severity)), h('td', {}, label(i.type)), h('td', {}, docCell(i.tenant_id, i.document_id)),
        h('td', { class: 'muted' }, i.title), h('td', { class: 'muted small' }, ago(i.last_seen_at))))))),
      h('div', { class: 'row between', style: { marginTop: '10px' } }, h('span', { class: 'muted small' }, `${f.offset + 1}-${f.offset + data.items.length} of ${num(data.total)}`),
        h('div', { class: 'row' }, h('button', { class: 'btn sm', disabled: f.offset === 0, onclick: () => { f.offset = Math.max(0, f.offset - 50); refresh(); } }, 'Previous'),
          h('button', { class: 'btn sm', disabled: f.offset + 50 >= data.total, onclick: () => { f.offset += 50; refresh(); } }, 'Next'))));
  }
  await refresh();
}

async function openIssue(id) {
  const i = await api('/api/issues/' + encodeURIComponent(id));
  const ev = i.evidence || {};
  const body = [
    h('div', { class: 'row' }, pill(i.severity), pill(i.status), h('span', { class: 'muted' }, label(i.type)), docCell(i.tenant_id, i.document_id)),
    h('p', {}, i.detail),
    h('div', { class: 'notice' }, h('strong', {}, 'Recommended action: '), ACTIONS[i.action] || i.action),
  ];
  if (ev.pipeline_reported_success) body.push(h('div', { class: 'notice warn' }, 'The processing pipeline reported success for this document. Job status alone would not have caught this.'));
  if (ev.retrieval_probe && ev.retrieval_probe.results) {
    const p = ev.retrieval_probe;
    body.push(h('div', { class: 'card' }, h('h3', {}, 'Retrieval probe'),
      h('p', { class: p.reachable ? '' : 'muted' }, p.reachable ? `This content is returned at rank ${p.rank} (score ${p.score}) for a query that matches it, scoped to tenant ${p.tenant_filter}.` : 'Not returned in the top results.'),
      h('table', {}, h('tbody', {}, p.results.map((r) => h('tr', {}, h('td', {}, '#' + r.rank), h('td', { class: 'mono' }, r.document_id || '-'), h('td', {}, r.score),
        h('td', {}, r.is_stale_content ? pill('stale content', 'critical') : h('span', { class: 'muted' }, 'current')))))),
      h('p', { class: 'small muted' }, p.method)));
  }
  if (ev.problems) body.push(h('div', {}, h('h3', {}, 'Problems'), h('ul', {}, ev.problems.map((p) => h('li', {}, pill(p.severity), ' ', p.message)))));
  const flat = {};
  for (const [k, v] of Object.entries(ev)) if (!['retrieval_probe', 'problems', 'removal_points', 'missing_chunks'].includes(k) && (typeof v !== 'object' || Array.isArray(v))) flat[k] = v;
  body.push(h('div', {}, h('h3', {}, 'Evidence'), dl(flat)));
  if (ev.missing_chunks && ev.missing_chunks.length) body.push(h('div', {}, h('h3', {}, `Missing chunks (${ev.missing_count})`), h('div', {}, ev.missing_chunks.slice(0, 30).map((c) => h('span', { class: 'chip mono' }, c)))));
  if (ev.removal_count) body.push(h('div', { class: 'notice' }, `${num(ev.removal_count)} vector(s) are candidates for removal. They are only handed to your worker after replacements are verified and you approve it.`));
  body.push(jsonBlock(ev));
  body.push(h('div', {}, h('h3', {}, 'Timeline'), h('ul', { class: 'timeline' }, i.events.map((e) =>
    h('li', {}, h('span', { class: 'when' }, fmtTime(e.ts)), h('span', {}, e.event.replace(/_/g, ' '), e.details && e.details.reason ? ' - ' + e.details.reason : ''))))));
  body.push(h('div', { class: 'row' },
    h('button', { class: 'btn primary', onclick: () => openDocument(i.tenant_id, i.document_id) }, 'Inspect document live'),
    i.status === 'ignored' ? h('button', { class: 'btn', onclick: async () => { await post(`/api/issues/${id}/reopen`); closeDrawer(); toast('Issue reopened'); render(); } }, 'Reopen')
      : i.status === 'open' ? h('button', { class: 'btn', onclick: async () => {
        const reason = window.prompt('Why are you ignoring this issue? (kept in the audit trail)', 'Known and accepted');
        if (reason === null) return; await post(`/api/issues/${id}/ignore`, { reason }); closeDrawer(); toast('Issue ignored'); render(); } }, 'Ignore') : null));
  openDrawer(i.title, ...body);
}

async function openDocument(tenant, doc) {
  openDrawer(doc, h('div', { class: 'skeleton' }), h('div', { class: 'skeleton' }));
  const p = new URLSearchParams({ tenant, document_id: doc, live: 'true' });
  const data = await api('/api/document?' + p);
  const L = data.live;
  const fp = (o) => (o ? Object.entries(o).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · ') : '-');
  const classes = L.index.by_class || {};
  const present = new Set(L.index.chunks.filter((c) => ['fresh', 'unknown'].includes(c.class)).map((c) => c.chunk_id));
  const missing = L.expected_chunks.filter((c) => !present.has(c.chunk_id));
  const grid = h('div', { class: 'chunks' },
    L.index.chunks.map((c) => h('span', { class: 'chunk ' + c.class, title: `${c.class} · ${c.chunk_id}${c.copies > 1 ? ' · ' + c.copies + ' copies' : ''}` }, (c.chunk_index ?? '?') + (c.copies > 1 ? ' x' + c.copies : ''))),
    missing.map((c) => h('span', { class: 'chunk missing', title: 'missing from the index · ' + c.chunk_id }, c.chunk_index ?? '?')));
  openDrawer(doc,
    h('div', { class: 'row' }, docCell(tenant, doc), pill(L.status)),
    h('div', { class: 'compare' },
      h('div', { class: 'col' }, h('h3', {}, 'Source (S3)'), L.source ? dl({ uri: L.source.source_uri, hash: short(L.source.source_hash), version: L.source.source_version, size: L.source.size_bytes + ' B', modified: fmtTime(L.source.last_modified) }) : h('p', { class: 'muted' }, 'Not in the source: deleted.')),
      h('div', { class: 'col' }, h('h3', {}, 'Manifest (Postgres)'), L.manifest ? dl({ status: L.manifest.processing_status, hash: short(L.manifest.source_hash), 'expected chunks': L.manifest.expected_chunk_count, 'indexed chunks': L.manifest.indexed_chunk_count, pipeline: fp(L.manifest.fingerprint), updated: fmtTime(L.manifest.updated_at) }) : h('p', { class: 'muted' }, 'No manifest row.')),
      h('div', { class: 'col' }, h('h3', {}, 'Index (Qdrant)'), L.index.points ? dl({ vectors: L.index.points, collections: L.index.collections, ...classes }) : h('p', { class: 'muted' }, 'No vectors.'))),
    h('div', {}, h('h3', {}, 'Chunks'), L.index.chunks.length || missing.length ? grid : h('p', { class: 'muted' }, 'No chunks indexed.'),
      h('div', { class: 'legend', style: { marginTop: '8px' } }, ['fresh', 'stale', 'outdated', 'unknown', 'orphan'].map((c) => h('span', {}, h('i', { class: 'chunk ' + c, style: { minWidth: '10px', height: '10px', padding: 0 } }), c)), h('span', {}, h('i', { style: { border: '1.5px dashed var(--crit)' } }), 'missing'))),
    h('div', {}, h('h3', {}, 'Findings'), L.findings.length ? h('ul', {}, L.findings.map((f) => h('li', {}, pill(f.severity), ' ', h('strong', {}, label(f.type)), ' - ', f.detail))) : h('p', { class: 'notice good' }, 'No findings. This document is consistent across source, manifest and index.')),
    L.index.fingerprints.length ? h('div', {}, h('h3', {}, 'Pipeline fingerprints in the index'), L.index.fingerprints.map((f) => h('p', { class: 'small' }, fp(f)))) : null,
    jsonBlock(L, 'Raw inspection data'));
}

async function viewDocuments(root) {
  const f = state.docFilters;
  const card = h('div', { class: 'card' });
  const search = h('input', { type: 'search', placeholder: 'Search document id', 'aria-label': 'Search', value: f.q });
  search.addEventListener('keydown', (e) => { if (e.key === 'Enter') { f.q = search.value; f.offset = 0; refresh(); } });
  append(root, h('div', { class: 'filters' },
    h('select', { 'aria-label': 'Status', onchange: (e) => { f.status = e.target.value; f.offset = 0; refresh(); } },
      [['', 'All statuses'], ['broken', 'Broken'], ['degraded', 'Degraded'], ['orphaned', 'Orphaned'], ['pending', 'Pending'], ['healthy', 'Healthy']].map(([v, l]) => h('option', { value: v, selected: f.status === v }, l))),
    f.tenant ? h('button', { class: 'btn sm', onclick: () => { delete f.tenant; render(); } }, 'Tenant: ' + f.tenant + ' (clear)') : null, search,
    h('a', { class: 'btn sm', href: '#', onclick: async (e) => { e.preventDefault(); const t = await api('/api/report?format=md'); download('rag-integrity-report.md', t, 'text/markdown'); } }, 'Download report (.md)'),
    h('a', { class: 'btn sm', href: '#', onclick: async (e) => { e.preventDefault(); const t = await api('/api/report?format=csv'); download('rag-integrity-report.csv', t, 'text/csv'); } }, 'CSV')), card);
  async function refresh() {
    const p = new URLSearchParams({ limit: 50, offset: f.offset });
    if (f.status) p.set('status', f.status); if (f.q) p.set('q', f.q); if (f.tenant) p.set('tenant', f.tenant);
    const data = await api('/api/documents?' + p);
    clear(card);
    if (!data.items.length) { card.append(empty('No documents match.')); return; }
    card.append(h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Status', 'Document', 'Issues', 'Chunks (indexed / expected)', 'Embedding model', 'Verified'].map((x) => h('th', {}, x)))),
      h('tbody', {}, data.items.map((d) => h('tr', { class: 'click', tabindex: 0, onclick: () => openDocument(d.tenant_id, d.document_id), onkeydown: (e) => { if (e.key === 'Enter') openDocument(d.tenant_id, d.document_id); } },
        h('td', {}, pill(d.status)), h('td', {}, docCell(d.tenant_id, d.document_id)),
        h('td', {}, d.issue_types.length ? d.issue_types.map((t) => h('span', { class: 'chip' }, label(t))) : h('span', { class: 'muted' }, '-')),
        h('td', {}, `${num(d.indexed_chunks)} / ${d.expected_chunks == null ? '?' : num(d.expected_chunks)}`),
        h('td', { class: 'muted small' }, (d.fingerprint && d.fingerprint.embedding_model) || '-'), h('td', { class: 'muted small' }, ago(d.last_verified_at))))))),
      h('div', { class: 'row between', style: { marginTop: '10px' } }, h('span', { class: 'muted small' }, `${f.offset + 1}-${f.offset + data.items.length} of ${num(data.total)}`),
        h('div', { class: 'row' }, h('button', { class: 'btn sm', disabled: f.offset === 0, onclick: () => { f.offset = Math.max(0, f.offset - 50); refresh(); } }, 'Previous'),
          h('button', { class: 'btn sm', disabled: f.offset + 50 >= data.total, onclick: () => { f.offset += 50; refresh(); } }, 'Next'))));
  }
  await refresh();
}

function download(name, text, type) {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}

// ---- repairs
const STEPS = ['Plan', 'Reindex', 'Verify', 'Cleanup', 'Done'];
function stepOf(status) { return { draft: 0, triggered: 1, partial: 2, failed: 2, cleanup_pending: 3, cleanup_triggered: 3, completed: 4 }[status] ?? 0; }

async function viewRepairs(root, planId) {
  if (planId) return viewPlan(root, planId);
  const ov = state.ov;
  const sev = h('select', { 'aria-label': 'Minimum severity' }, [['', 'All open issues'], ['medium', 'Medium and above'], ['high', 'High and above'], ['critical', 'Critical only']].map(([v, l]) => h('option', { value: v }, l)));
  const tenant = h('select', { 'aria-label': 'Tenant' }, h('option', { value: '' }, 'All tenants'), ov.documents.tenants.map((t) => h('option', { value: t.tenant_id }, t.tenant_id)));
  const plans = await api('/api/repairs');
  append(root, h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', {}, 'New repair plan'),
      h('p', { class: 'muted', style: { marginBottom: '12px' } }, 'The platform never writes to your systems. It asks your own ingestion worker to repair, then independently verifies the result.'),
      h('div', { class: 'row' }, h('label', { class: 'f' }, 'Scope', sev), h('label', { class: 'f' }, 'Tenant', tenant),
        h('button', { class: 'btn primary', style: { alignSelf: 'flex-end' }, onclick: async (e) => {
          e.target.disabled = true;
          try { const p = await post('/api/repairs', { min_severity: sev.value || null, tenant: tenant.value || null }); location.hash = '#/repairs/' + p.id; } catch (err) { toast(err.message, true); e.target.disabled = false; } } }, 'Create plan'))),
    h('div', { class: 'card' }, h('h2', {}, 'Plans'),
      plans.length ? h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ['Created', 'Status', 'Documents', 'Est. cost', 'Savings vs full reindex'].map((x) => h('th', {}, x)))),
        h('tbody', {}, plans.map((p) => h('tr', { class: 'click', onclick: () => { location.hash = '#/repairs/' + p.id; } }, h('td', {}, fmtTime(p.created_at)), h('td', {}, pill(p.status)),
          h('td', {}, num(p.summary.documents_affected)), h('td', {}, money(p.summary.estimated_cost_usd)), h('td', {}, p.summary.savings_vs_full_reindex_pct == null ? '-' : p.summary.savings_vs_full_reindex_pct + '%')))))) : empty('No repair plans yet.'))));
}

async function viewPlan(root, id) {
  const p = await api('/api/repairs/' + encodeURIComponent(id));
  const s = p.summary, cur = stepOf(p.status), bad = ['partial', 'failed'].includes(p.status);
  const run = (fn, msg) => async (e) => {
    e.target.disabled = true;
    try { await fn(); toast(msg); } catch (err) { toast(err.message, true); }
    render();
  };
  const act = [];
  if (p.status === 'draft') act.push(h('button', { class: 'btn primary', onclick: run(() => post(`/api/repairs/${id}/trigger`), 'Repair handed to your worker') }, 'Trigger repair worker'));
  if (['triggered', 'partial', 'failed', 'cleanup_triggered', 'cleanup_pending'].includes(p.status)) act.push(h('button', { class: p.status === 'triggered' || p.status === 'cleanup_triggered' ? 'btn primary' : 'btn', onclick: run(() => post(`/api/repairs/${id}/verify`), 'Verification finished') }, 'Verify now'));
  if (['partial', 'failed'].includes(p.status)) act.push(h('button', { class: 'btn', onclick: run(() => post(`/api/repairs/${id}/trigger`), 'Failed documents re-sent to your worker') }, 'Re-trigger failed documents'));
  if (['cleanup_pending', 'partial'].includes(p.status) && p.items.some((i) => ['reindexed', 'awaiting_cleanup'].includes(i.status))) {
    act.push(h('button', { class: 'btn danger', onclick: (e) => { if (window.confirm('Ask your worker to remove the superseded vectors for documents that passed verification? Documents that failed keep their old vectors.')) run(() => post(`/api/repairs/${id}/approve-cleanup`), 'Cleanup requested')(e); } }, 'Approve cleanup'));
  }
  act.push(h('button', { class: 'btn ghost', onclick: async () => { const pl = await api(`/api/repairs/${id}/payload`); openDrawer('Webhook payload (reindex phase)', h('p', { class: 'muted' }, 'Signed with HMAC-SHA256 and sent to your repair webhook.'), h('pre', {}, JSON.stringify(pl, null, 2))); } }, 'Preview payload'));
  const checkNames = [['expected_chunks_present', 'All expected chunks present'], ['embeddings_present', 'Embeddings present'], ['latest_version_indexed', 'Latest version indexed'], ['metadata_correct', 'Metadata correct'], ['old_vectors_inactive', 'Old vectors inactive']];
  append(root, h('div', { class: 'stack' },
    h('div', { class: 'row' }, h('a', { href: '#/repairs' }, '← All plans'), pill(p.status), h('span', { class: 'muted small mono' }, p.id)),
    h('div', { class: 'stepper' }, STEPS.map((n, i) => h('div', { class: 'step ' + (i < cur || p.status === 'completed' ? 'done' : i === cur ? (bad ? 'bad' : 'now') : '') }, h('div', { class: 'n' }, 'Step ' + (i + 1)), n))),
    bad ? h('div', { class: 'notice warn' }, 'Some documents failed verification: the worker reported success but the index does not match the source. Failed documents keep their old vectors, and nothing is removed for them.') : null,
    p.status === 'cleanup_pending' ? h('div', { class: 'notice' }, 'Replacements are verified. Superseded vectors are still active; removal needs your approval (cleanup policy: manual).') : null,
    h('div', { class: 'grid g4' }, kpi(num(s.documents_affected), 'documents in plan'), kpi(num(s.chunks_to_regenerate), 'chunks to regenerate'),
      kpi(money(s.estimated_cost_usd), `est. embedding cost (${num(s.estimated_tokens)} tokens)`), kpi(s.savings_vs_full_reindex_pct == null ? '-' : s.savings_vs_full_reindex_pct + '%', 'saved vs re-embedding everything')),
    h('div', { class: 'row' }, act),
    h('div', { class: 'card' }, h('h2', {}, 'Documents'), h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Severity', 'Document', 'Actions', 'Status', 'Verification'].map((x) => h('th', {}, x)))),
      h('tbody', {}, p.items.map((it) => h('tr', { class: 'click', onclick: () => openDocument(it.tenant_id, it.document_id) },
        h('td', {}, pill(it.worst_severity)), h('td', {}, docCell(it.tenant_id, it.document_id)),
        h('td', {}, it.actions.map((a) => h('span', { class: 'chip' }, a.replace(/_/g, ' '))), it.cleanup ? h('span', { class: 'chip' }, `remove ${num(it.cleanup_vectors)} vectors later`) : null),
        h('td', {}, pill(it.status)),
        h('td', {}, Object.keys(it.checks || {}).length ? h('span', { class: 'checks' }, checkNames.map(([k, t]) => h('span', { class: 'ck ' + (it.checks[k] ? 'ok' : 'no'), title: t + (it.checks[k] ? ': pass' : ': FAIL') }, it.checks[k] ? '✓' : '✕'))) : h('span', { class: 'muted small' }, 'not verified yet')))))))),
    h('div', { class: 'card' }, h('h2', {}, 'Activity'), h('ul', { class: 'timeline' }, p.events.map((e) => h('li', {}, h('span', { class: 'when' }, fmtTime(e.ts)),
      h('span', {}, h('strong', {}, e.event.replace(/_/g, ' ')), e.details && e.details.result ? ' → ' + e.details.result : '', e.details && e.details.failed_documents && e.details.failed_documents.length ? ' (failed: ' + e.details.failed_documents.length + ')' : '')))))));
}

// ---- impact
async function viewImpact(root) {
  const rec = await api('/api/recommendations');
  const s = rec.summary, fc = s.full_corpus;
  const out = h('div', { class: 'stack' });
  const scenario = h('select', { 'aria-label': 'Scenario' }, [['open_issues', 'Current open issues'], ['config_change', 'Pipeline config change'], ['ingestion_failure', 'Ingestion failure window']].map(([v, l]) => h('option', { value: v }, l)));
  const fields = h('div', { class: 'row' });
  const inputs = { embedding_model: h('input', { type: 'text', placeholder: 'e.g. text-embedding-3-large' }), chunking_version: h('input', { type: 'text', placeholder: 'e.g. recursive-v3' }), chunk_size: h('input', { type: 'text', placeholder: 'e.g. 800' }),
    since: h('input', { type: 'datetime-local' }) };
  const wrap = (k, t) => h('label', { class: 'f', 'data-for': k }, t, inputs[k]);
  const showFields = () => { clear(fields); if (scenario.value === 'config_change') append(fields, [wrap('embedding_model', 'Embedding model'), wrap('chunking_version', 'Chunking version'), wrap('chunk_size', 'Chunk size')]); if (scenario.value === 'ingestion_failure') append(fields, [wrap('since', 'Failure started')]); };
  scenario.addEventListener('change', showFields); showFields();
  const result = h('div', { class: 'stack' });
  append(root, h('div', { class: 'stack' },
    h('div', { class: 'card' }, h('h2', {}, 'Safe reindex recommendation'),
      s.documents_affected ? h('div', { class: 'stack' },
        h('p', { class: 'muted' }, `Repair ${num(s.documents_to_reprocess)} document(s) instead of re-embedding the corpus of ${num(fc.documents)}.`),
        h('div', { class: 'grid g4' }, kpi(num(s.full_reindex_documents), 'full reindex'), kpi(num(s.chunk_reindex_documents), 'chunk-level reindex'), kpi(num(s.metadata_fix_documents), 'metadata fix only (no embedding)'), kpi(num(s.vectors_to_remove), 'superseded vectors to remove later')),
        h('div', { class: 'save' }, h('span', {}, 'Targeted'), meter(s.estimated_tokens, fc.estimated_tokens), h('strong', {}, money(s.estimated_cost_usd))),
        h('div', { class: 'save' }, h('span', {}, 'Full reindex'), meter(fc.estimated_tokens, fc.estimated_tokens), h('strong', {}, money(fc.estimated_cost_usd))),
        h('p', {}, h('strong', {}, s.savings_vs_full_reindex_pct == null ? '' : s.savings_vs_full_reindex_pct + '% less embedding work'), ' · tenants: ', s.tenants_affected.join(', '), ' · collections: ', s.collections_affected.join(', ') || '-'),
        h('p', { class: 'small muted' }, s.assumptions)) : empty('Nothing to repair.')),
    h('div', { class: 'card' }, h('h2', {}, 'Blast radius'),
      h('p', { class: 'muted', style: { marginBottom: '12px' } }, 'What is affected by a failure or a planned change, and how much will it cost to fix?'),
      h('div', { class: 'row' }, h('label', { class: 'f' }, 'Scenario', scenario), fields,
        h('button', { class: 'btn primary', style: { alignSelf: 'flex-end' }, onclick: async (e) => {
          e.target.disabled = true; clear(result);
          const sc = { type: scenario.value };
          if (sc.type === 'config_change') { sc.target = {}; for (const k of ['embedding_model', 'chunking_version']) if (inputs[k].value.trim()) sc.target[k] = inputs[k].value.trim(); if (inputs.chunk_size.value.trim()) sc.target.chunk_size = Number(inputs.chunk_size.value); }
          if (sc.type === 'ingestion_failure' && inputs.since.value) sc.since = new Date(inputs.since.value).toISOString();
          try { result.append(blastView(await post('/api/blast-radius', { scenario: sc }))); } catch (err) { result.append(h('div', { class: 'notice warn' }, err.message)); }
          e.target.disabled = false; } }, 'Analyse')), result)));
}
function blastView(b) {
  const q = b.queries, w = b.workload;
  return h('div', { class: 'stack', style: { marginTop: '14px' } }, h('p', {}, b.description),
    h('div', { class: 'grid g4' }, kpi(`${num(b.documents.affected)} / ${num(b.documents.total)}`, `documents affected (${b.documents.affected_pct}%)`),
      kpi(num(b.tenants.length), 'tenants affected'), kpi(q.affected_queries == null || !q.queries_in_window ? '-' : `${num(q.affected_queries)} (${q.affected_pct}%)`, `queries touching them, last ${q.window_days} days`),
      kpi(money(w.estimated_cost_usd), `to re-embed ${num(w.chunks_to_regenerate)} chunks`)),
    q.note ? h('p', { class: 'muted small' }, q.note) : null,
    b.tenants.length ? h('table', {}, h('thead', {}, h('tr', {}, ['Tenant', 'Affected', 'Total'].map((x) => h('th', {}, x)))), h('tbody', {}, b.tenants.map((t) => h('tr', {}, h('td', {}, t.tenant_id), h('td', {}, num(t.affected)), h('td', {}, num(t.total)))))) : null,
    q.top_documents.length ? h('div', {}, h('h3', {}, 'Most-queried affected documents'), h('table', {}, h('tbody', {}, q.top_documents.map((d) => h('tr', {}, h('td', {}, docCell(d.tenant_id, d.document_id)), h('td', {}, num(d.queries) + ' queries')))))) : null,
    Object.keys(b.by_issue_type).length ? h('div', {}, b.by_issue_type && Object.entries(b.by_issue_type).map(([t, n]) => h('span', { class: 'chip' }, `${label(t)}: ${n}`))) : null);
}

// ---- history & connections
async function viewHistory(root) {
  const items = await api('/api/history?limit=150');
  const text = (e) => {
    if (e.kind === 'audit') return `Audit ${e.event.replace('audit_', '')} (${e.details.kind}, ${e.details.trigger}) - ${e.details.findings ?? '?'} findings, health ${e.details.health_score ?? '?'}%`;
    if (e.kind === 'repair') return `Repair plan ${e.plan_id.slice(0, 8)}: ${e.event.replace(/_/g, ' ')}`;
    return `${e.event.replace(/_/g, ' ')}: ${e.title} - ${e.tenant_id}/${e.document_id}`;
  };
  append(root, h('div', { class: 'card' }, items.length ? h('ul', { class: 'timeline' }, items.map((e) => h('li', {}, h('span', { class: 'when' }, fmtTime(e.ts)),
    h('span', {}, e.severity ? pill(e.severity) : null, e.severity ? ' ' : '', text(e))))) : empty('No history yet.')));
}

async function viewConnections(root) {
  const [conns] = await Promise.all([api('/api/connections')]);
  const ov = state.ov;
  append(root, h('div', { class: 'stack' },
    h('div', { class: 'grid g2' }, conns.map((c) => h('div', { class: 'card' }, h('div', { class: 'row between' }, h('h2', {}, c.name), pill(c.ok ? 'connected' : 'failing', c.ok ? 'healthy' : 'failed')),
      h('p', { class: c.ok ? 'muted' : '' }, c.detail), c.latency_ms ? h('p', { class: 'small muted' }, Math.round(c.latency_ms) + ' ms') : null,
      c.info && c.info.missing && c.info.missing.length ? h('p', { class: 'small muted' }, 'Unmapped optional columns: ' + c.info.missing.join(', ')) : null))),
    h('div', { class: 'card' }, h('h2', {}, 'Configuration'),
      dl({ mode: ov.mode, 'cleanup policy': ov.cleanup_policy, 'scheduled audits': ov.scheduler_interval_minutes ? `every ${ov.scheduler_interval_minutes} min` : 'off (use cron or POST /api/audits)',
        'repair webhook': ov.repair_webhook_configured ? 'configured' : 'not configured', 'target pipeline': ov.target_fingerprint ? Object.entries(ov.target_fingerprint).map(([k, v]) => `${k}=${v}`).join(', ') : 'not set (drift check limited to mixed configs)' }),
      h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Connectors are read-only. Credentials come from the server environment and are never stored in the ledger.'))));
}

// ---------------------------------------------------------------- shell
function go(view) { location.hash = '#/' + view; }
function route() { const [, view = 'overview', arg] = location.hash.split('/'); return { view: VIEWS.some((v) => v.id === view) ? view : 'overview', arg }; }

async function refreshOverview() { state.ov = await api('/api/overview'); return state.ov; }
function renderNav() {
  const { view } = route(), nav = clear($('#nav'));
  for (const v of VIEWS) {
    const badge = v.id === 'issues' && state.ov && state.ov.issues.open ? h('span', { class: 'count' }, num(state.ov.issues.open)) : null;
    nav.append(h('a', { href: '#/' + v.id, 'aria-current': v.id === view ? 'page' : null }, h('span', {}, v.label), badge));
  }
}
let renderToken = 0;
async function render() {
  const token = ++renderToken, { view, arg } = route(), root = clear($('#view'));
  const meta = VIEWS.find((v) => v.id === view);
  $('#view-title').textContent = meta.label; $('#view-sub').textContent = meta.sub; document.title = meta.label + ' · RAG Integrity';
  root.append(h('div', { class: 'card' }, h('div', { class: 'skeleton' })));
  try {
    await refreshOverview();
    if (token !== renderToken) return;
    renderChrome(); clear(root);
    await ({ overview: viewOverview, issues: viewIssues, documents: viewDocuments, repairs: viewRepairs, impact: viewImpact, history: viewHistory, connections: viewConnections }[view])(root, arg);
    if (state.ov.audit_running) pollAudit();
  } catch (err) {
    if (token !== renderToken) return;
    clear(root).append(h('div', { class: 'card' }, h('h2', {}, 'Something went wrong'), h('p', {}, err.message)));
  }
}
function renderChrome() {
  renderNav();
  const ov = state.ov;
  const badge = $('#mode-badge'); badge.textContent = ov.demo ? 'Demo' : 'Live'; badge.className = 'badge ' + (ov.demo ? 'demo' : 'live');
  $('#btn-reset').hidden = !ov.demo;
  const banner = $('#banner');
  banner.hidden = !ov.demo; banner.className = 'banner';
  if (ov.demo) banner.textContent = 'Demo mode: a synthetic multi-tenant corpus with deliberately injected faults. Nothing here touches real infrastructure.';
  $('#btn-audit').disabled = ov.audit_running; $('#btn-audit').textContent = ov.audit_running ? 'Auditing…' : 'Run audit';
}
async function pollAudit() {
  if (state.polling) return; state.polling = true;
  try {
    for (let i = 0; i < 600; i++) {
      await new Promise((r) => setTimeout(r, 1200));
      const ov = await refreshOverview();
      if (!ov.audit_running) { toast(`Audit finished: ${num(ov.issues.open)} open issue(s), health ${ov.documents.health_score}%`); break; }
    }
  } finally { state.polling = false; }
  render();
}

async function boot() {
  $('#drawer-close').addEventListener('click', closeDrawer);
  $('#scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#drawer').hidden) closeDrawer(); });
  $('#btn-audit').addEventListener('click', async (e) => {
    e.target.disabled = true;
    try { const r = await post('/api/audits'); toast(r.status === 'completed' ? 'Audit finished' : 'Audit started'); render(); } catch (err) { toast(err.message, true); e.target.disabled = false; }
  });
  $('#btn-reset').addEventListener('click', async (e) => {
    if (!window.confirm('Regenerate the demo world and clear the ledger?')) return;
    e.target.disabled = true;
    try { await post('/api/demo/reset'); toast('Demo world regenerated'); } catch (err) { toast(err.message, true); }
    e.target.disabled = false; render();
  });
  $('#btn-key').addEventListener('click', () => askKey().then(render).catch(() => {}));
  try { const a = await api('/api/auth'); $('#btn-key').hidden = !a.required; } catch (_) { /* ignore */ }
  try { const hz = await api('/healthz'); $('#version').textContent = 'v' + hz.version; } catch (_) { /* ignore */ }
  window.addEventListener('hashchange', render);
  render();
}
boot();
})();
