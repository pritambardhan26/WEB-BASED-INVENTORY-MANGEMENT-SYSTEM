/* ══════════════════════════════════════════════════════════════
   main.js  —  IMS Global Utilities  (upgraded)
   ──────────────────────────────────────────────────────────────
   Improvements applied:
     #1  apiCall      — AbortController timeout + auto-retry
     #2  showToast    — dedup + max-4 cap
     #3  makeSortable — ▲ / ▼ sort indicators
     #4  exportCSV    — UTF-8 BOM (Excel ₹ fix)
     #5  debounce()   — new reusable helper
     #6  formatDate() — new canonical date formatter
     #7  renderPaginator() — new reusable paginator
     #8  showSkeleton()   — new shimmer loader
     #9  getCsrf     — cached (no repeated DOM queries)
     #10 initTabs    — localStorage tab persistence
   ══════════════════════════════════════════════════════════════ */


/* ── #9  CSRF — cached single lookup ─────────────────────────── */
let _csrfCache = null;
function getCsrf() {
  if (_csrfCache) return _csrfCache;
  const m = document.cookie.match(/csrf_token=([^;]+)/);
  if (m) return (_csrfCache = decodeURIComponent(m[1]));
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) return (_csrfCache = meta.getAttribute('content'));
  const inp = document.querySelector('input[name="csrf_token"]');
  return (_csrfCache = inp?.value || '');
}


/* ── #1  API CALL — timeout + auto-retry ─────────────────────── */
/**
 * Fetch wrapper with:
 *   - 8-second AbortController timeout
 *   - 1 automatic retry on network failure
 *   - Unified error toasts
 *
 * @param {string}  url
 * @param {string}  method   GET | POST | PUT | DELETE
 * @param {object}  body     JSON-serialisable payload (optional)
 * @param {number}  retries  How many extra attempts on failure (default 1)
 * @returns {object|null}    Parsed JSON or null on error
 */
async function apiCall(url, method = 'GET', body = null, retries = 1) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken':  getCsrf(),
    },
  };
  if (body) opts.body = JSON.stringify(body);

  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);   // 8-second timeout

    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal });
      clearTimeout(timer);

      if (!r.ok) {
        const text = await r.text();
        console.error(`[apiCall] ${method} ${url} → ${r.status}`, text);
        showToast(`Server error ${r.status}`, 'danger');
        return null;
      }
      return await r.json();

    } catch (e) {
      clearTimeout(timer);
      const isLast = attempt === retries;
      if (e.name === 'AbortError') {
        if (isLast) { showToast('Request timed out. Check your connection.', 'danger'); return null; }
      } else {
        if (isLast) { showToast('Network error: ' + e.message, 'danger'); return null; }
      }
      // small back-off before retry
      await new Promise(res => setTimeout(res, 400 * (attempt + 1)));
    }
  }
  return null;
}


/* ── #2  TOAST — dedup + max-4 cap ──────────────────────────── */
const _activeToastMsgs = new Set();

function showToast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  // dedup — skip if the same message is already on screen
  if (_activeToastMsgs.has(msg)) return;

  // cap — remove oldest toast if 4 are already visible
  const live = container.querySelectorAll('.toast.show');
  if (live.length >= 4) {
    live[0].querySelector('[data-bs-dismiss="toast"]')?.click();
  }

  const icons = {
    success: 'check-circle-fill',
    danger:  'x-circle-fill',
    warning: 'exclamation-triangle-fill',
    info:    'info-circle-fill',
  };
  const id = 'toast_' + Date.now();
  const html = `
    <div id="${id}" class="toast align-items-center text-bg-${type} border-0 shadow" role="alert">
      <div class="d-flex">
        <div class="toast-body d-flex align-items-center gap-2">
          <i class="bi bi-${icons[type] || 'info-circle-fill'}"></i>
          ${escHtml(msg)}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto"
                data-bs-dismiss="toast"></button>
      </div>
    </div>`;

  container.insertAdjacentHTML('beforeend', html);
  _activeToastMsgs.add(msg);

  const el    = document.getElementById(id);
  const toast = new bootstrap.Toast(el, { delay: 4000 });
  toast.show();
  el.addEventListener('hidden.bs.toast', () => {
    _activeToastMsgs.delete(msg);
    el.remove();
  });
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}


/* ── CLOCK ───────────────────────────────────────────────────── */
function startClock() {
  const el = document.getElementById('topbarClock');
  if (!el) return;
  const tick = () => {
    el.textContent = new Date().toLocaleString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    });
  };
  tick();
  setInterval(tick, 1000);
}


/* ── SIDEBAR ─────────────────────────────────────────────────── */
function initSidebar() {
  const toggle  = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  if (!toggle || !sidebar) return;
  toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
}


/* ── #10  TABS — with localStorage persistence ───────────────── */
/**
 * @param {string} containerSel  CSS selector for the tab container
 * @param {string} storageKey    localStorage key for persistence
 */
function initTabs(containerSel = '.ims-tabs', storageKey = 'ims_activeTab') {
  document.querySelectorAll(containerSel).forEach(group => {
    const tabs  = group.querySelectorAll('.ims-tab');
    const saved = localStorage.getItem(storageKey);

    const activate = (tab) => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.dataset.tab;
      document.querySelectorAll('.ims-tab-pane').forEach(p => {
        p.classList.toggle('active', p.id === target);
      });
      localStorage.setItem(storageKey, target);
    };

    tabs.forEach(tab => {
      tab.addEventListener('click', () => activate(tab));
      // restore saved tab on load
      if (saved && tab.dataset.tab === saved) activate(tab);
    });
  });
}


/* ── #3  SORTABLE TABLE — ▲ / ▼ indicators ───────────────────── */
function makeSortable(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const headers = table.querySelectorAll('thead th');
  headers.forEach((th, colIdx) => {
    th.style.cursor = 'pointer';
    th.style.userSelect = 'none';
    let ascending = true;

    th.addEventListener('click', () => {
      const tbody = table.querySelector('tbody');
      const rows  = Array.from(tbody.rows);

      rows.sort((a, b) => {
        const av = a.cells[colIdx]?.textContent.trim() || '';
        const bv = b.cells[colIdx]?.textContent.trim() || '';
        const an = parseFloat(av.replace(/[^0-9.\-]/g, ''));
        const bn = parseFloat(bv.replace(/[^0-9.\-]/g, ''));
        if (!isNaN(an) && !isNaN(bn)) return ascending ? an - bn : bn - an;
        return ascending ? av.localeCompare(bv) : bv.localeCompare(av);
      });

      rows.forEach(r => tbody.appendChild(r));

      // clear all indicators, set this column's
      headers.forEach(h => {
        h.textContent = h.textContent.replace(/ [▲▼]$/, '');
        h.classList.remove('sorted-asc', 'sorted-desc');
      });
      th.textContent += ascending ? ' ▲' : ' ▼';
      th.classList.add(ascending ? 'sorted-asc' : 'sorted-desc');

      ascending = !ascending;
    });
  });
}


/* ── ROW SELECTION ───────────────────────────────────────────── */
function initRowSelect(tableId, onSelect) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.querySelectorAll('tbody').forEach(tbody => {
    tbody.addEventListener('click', e => {
      const row = e.target.closest('tr');
      if (!row) return;
      table.querySelectorAll('tbody tr').forEach(r => r.classList.remove('selected'));
      row.classList.add('selected');
      if (onSelect) onSelect(row);
    });
  });
}


/* ── #6  CANONICAL DATE FORMATTER ────────────────────────────── */
/**
 * @param {string|Date} iso   ISO string or Date object
 * @param {object}      opts  Intl.DateTimeFormat overrides
 * @returns {string}          Formatted date or '—' for empty values
 */
function formatDate(iso, opts = {}) {
  if (!iso) return '—';
  const d = iso instanceof Date ? iso : new Date(iso);
  if (isNaN(d)) return '—';
  return d.toLocaleString('en-IN', {
    day:    '2-digit',
    month:  'short',
    year:   'numeric',
    hour:   '2-digit',
    minute: '2-digit',
    hour12: true,
    ...opts,
  });
}

/** Date-only variant — no time component */
function formatDateOnly(iso) {
  return formatDate(iso, { hour: undefined, minute: undefined, hour12: undefined });
}


/* ── #5  DEBOUNCE ────────────────────────────────────────────── */
/**
 * Returns a debounced version of fn that fires after `ms` ms of silence.
 *
 * Usage:
 *   searchInput.addEventListener('input', debounce(() => loadData(), 350));
 */
function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}


/* ── #7  PAGINATOR RENDERER ──────────────────────────────────── */
/**
 * Renders a simple page-button strip inside containerId.
 * Expects the API response shape: { page, pages, total }
 *
 * @param {string}   containerId   ID of the <div> to render into
 * @param {object}   data          { page, pages, total }
 * @param {function} onPageChange  Called with the new page number
 *
 * Usage:
 *   const data = await apiCall('/customers/api/list?page=1');
 *   renderPaginator('customerPager', data, p => loadCustomers(p));
 */
function renderPaginator(containerId, data, onPageChange) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!data || data.pages <= 1) {
    el.innerHTML = '';
    return;
  }

  const { page, pages, total } = data;
  const window = 2;   // pages to show on each side of current

  const btnClass  = 'btn-ims btn-ghost-ims';
  const activeClz = 'btn-primary-ims';

  let html = `<div style="display:flex;align-items:center;gap:4px;justify-content:center;flex-wrap:wrap;margin-top:12px">`;

  // prev
  html += `<button class="${btnClass}" ${page <= 1 ? 'disabled' : ''}
              onclick="(${onPageChange.toString()})(${page - 1})">‹ Prev</button>`;

  // page buttons
  for (let p = 1; p <= pages; p++) {
    if (
      p === 1 || p === pages ||
      (p >= page - window && p <= page + window)
    ) {
      html += `<button class="${btnClass} ${p === page ? activeClz : ''}"
                  onclick="(${onPageChange.toString()})(${p})">${p}</button>`;
    } else if (
      p === page - window - 1 || p === page + window + 1
    ) {
      html += `<span style="padding:0 4px;color:var(--color-text-tertiary)">…</span>`;
    }
  }

  // next
  html += `<button class="${btnClass}" ${page >= pages ? 'disabled' : ''}
              onclick="(${onPageChange.toString()})(${page + 1})">Next ›</button>`;

  html += `<span style="font-size:.75rem;color:var(--color-text-tertiary);margin-left:8px">
              ${total} record${total !== 1 ? 's' : ''}</span>`;
  html += `</div>`;
  el.innerHTML = html;
}


/* ── #8  SKELETON LOADER ─────────────────────────────────────── */
/**
 * Replaces a tbody with shimmering placeholder rows while data loads.
 * Call showSkeleton() before fetch, then renderRows() when data arrives.
 *
 * @param {string} tbodyId  ID of the <tbody> element
 * @param {number} cols     Number of columns
 * @param {number} rows     Number of skeleton rows to show
 */
function showSkeleton(tbodyId, cols = 6, rows = 6) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;

  const cell = `<td style="padding:10px 14px">
    <div style="height:11px;border-radius:4px;
      background:var(--color-background-secondary);
      position:relative;overflow:hidden">
      <div style="position:absolute;inset:0;
        background:linear-gradient(90deg,transparent 0%,
          var(--color-border-tertiary) 50%,transparent 100%);
        animation:_shimmer 1.3s ease-in-out infinite;
        background-size:200% 100%"></div>
    </div></td>`;

  tbody.innerHTML = Array(rows)
    .fill(`<tr>${Array(cols).fill(cell).join('')}</tr>`)
    .join('');

  // inject keyframes once
  if (!document.getElementById('_shimmerStyle')) {
    const s = document.createElement('style');
    s.id = '_shimmerStyle';
    s.textContent = '@keyframes _shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}';
    document.head.appendChild(s);
  }
}


/* ── FORMAT HELPERS ──────────────────────────────────────────── */
/** Format number as Indian Rupee — ₹1,23,456.00 */
function fmt(n) {
  return '₹' + parseFloat(n || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Format as percentage — 12.50% */
function fmtPct(n) {
  return parseFloat(n || 0).toFixed(2) + '%';
}


/* ── RENDER ROWS ─────────────────────────────────────────────── */
function renderRows(tbodyId, rows, mapper) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;

  tbody.innerHTML = '';

  if (!rows || !rows.length) {
    tbody.innerHTML = `
      <tr><td colspan="20" class="text-center text-muted py-4">
        <i class="bi bi-inbox" style="font-size:1.5rem;opacity:.3"></i>
        <br>No records found
      </td></tr>`;
    return;
  }

  rows.forEach((row, i) => {
    const tr = document.createElement('tr');
    tr.style.background = i % 2 === 0 ? '' : '#FAFBFC';
    tr.innerHTML = mapper(row, i);
    tbody.appendChild(tr);
  });
}


/* ── #4  EXPORT CSV — UTF-8 BOM (Excel ₹ fix) ───────────────── */
function exportTableCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const rows = Array.from(table.querySelectorAll('tr'));
  const csv  = rows
    .map(r =>
      Array.from(r.querySelectorAll('th,td'))
        .map(c => '"' + c.textContent.trim().replace(/"/g, '""') + '"')
        .join(',')
    )
    .join('\n');

  // '\uFEFF' = UTF-8 BOM — tells Excel to read Unicode correctly
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = filename || 'export.csv';
  a.click();
  URL.revokeObjectURL(a.href);   // free memory
}


/* ── MISC HELPERS ────────────────────────────────────────────── */
function confirm2(msg) { return window.confirm(msg); }

function defaultDateRange(fromId, toId, days = 30) {
  const to   = new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - days);
  const iso  = d => d.toISOString().slice(0, 10);
  const fe   = document.getElementById(fromId);
  const te   = document.getElementById(toId);
  if (fe && !fe.value) fe.value = iso(from);
  if (te && !te.value) te.value = iso(to);
}


/* ── INIT ────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  initSidebar();
  initTabs();
});