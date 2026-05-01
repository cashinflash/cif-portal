/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL · MY LOANS
   List view (default) + detail view (?id=<loanId>).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  // ---------- Config ----------
  var API_BASE = '/api';
  var TOKEN_KEY = 'cif_id_token';
  var ACTIVE_ENDPOINT = API_BASE + '/my-loans/active';
  var DOCS_ENDPOINT = API_BASE + '/my-loans/documents';
  var LOGIN_URL = '/start.html';

  // ---------- Helpers ----------
  function qs(sel, root) { return (root || document).querySelector(sel); }

  function decodeJwt(t) {
    try {
      var p = t.split('.')[1];
      var b = p.replace(/-/g, '+').replace(/_/g, '/');
      var pad = b + '==='.slice((b.length + 3) % 4);
      return JSON.parse(decodeURIComponent(
        atob(pad).split('').map(function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      ));
    } catch (e) { return null; }
  }
  function isExpired(c) {
    if (!c || !c.exp) return true;
    return c.exp * 1000 < Date.now() + 15 * 1000;
  }

  function fmtCurrency(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
      style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }
  function fmtApr(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toFixed(2) + '%';
  }
  function fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  function fmtBool(v) {
    if (v === true) return 'Yes';
    if (v === false) return 'No';
    return '—';
  }
  function setText(el, v) { if (el) el.textContent = v; }

  function api(path, token) {
    return fetch(path, {
      method: 'GET',
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL);
        throw new Error('unauthorized');
      }
      if (!res.ok) {
        var err = new Error('http ' + res.status);
        err.status = res.status;
        throw err;
      }
      return res.json();
    });
  }

  // ---------- Auth guard ----------
  var token = sessionStorage.getItem(TOKEN_KEY);
  var claims = token ? decodeJwt(token) : null;
  if (!token || !claims || isExpired(claims)) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_URL);
    return;
  }

  // ---------- Init ----------
  document.addEventListener('DOMContentLoaded', function () {
    var first = (claims.given_name || '').trim();
    setText(qs('#userChip'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    setText(qs('#sidebarUserName'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    var year = qs('#footerYear');
    if (year) year.textContent = String(new Date().getFullYear());

    initDocModal();

    var params = new URLSearchParams(window.location.search);
    var loanIdParam = params.get('id');
    if (loanIdParam) {
      showDetail(loanIdParam);
    } else {
      showList();
    }
  });

  // ---------- LIST VIEW ----------
  function showList() {
    qs('#loansListView').hidden = false;
    qs('#loansDetailView').hidden = true;
    setText(qs('#loansTitle'), 'Your loan history');
    setText(qs('#loansSubtitle'), 'Every loan you’ve had with Cash in Flash, in one place.');

    api(ACTIVE_ENDPOINT, token)
      .then(function (data) {
        var loans = (data && data.allLoans) || [];
        renderList(loans);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderListError();
      });
  }

  function renderList(loans) {
    var body = qs('#loansListBody');
    var count = qs('#loansCount');
    if (!body) return;
    body.innerHTML = '';

    if (!loans || !loans.length) {
      var empty = document.createElement('div');
      empty.className = 'dash-loanlist-empty';
      empty.innerHTML =
        '<p style="margin-bottom:16px;">You don’t have any loans on file yet.</p>' +
        '<a href="/request-loan.html" class="btn-apply" data-action="new-loan">Request a loan</a>';
      body.appendChild(empty);
      if (count) count.hidden = true;
      return;
    }

    if (count) {
      count.textContent = loans.length + (loans.length === 1 ? ' loan' : ' loans');
      count.hidden = false;
    }

    // Newest first.
    var sorted = loans.slice().sort(function (a, b) {
      var da = new Date(a.loanDate || a.originationDate || 0).getTime();
      var db = new Date(b.loanDate || b.originationDate || 0).getTime();
      return db - da;
    });

    sorted.forEach(function (loan) {
      var row = document.createElement('a');
      row.className = 'dash-loanlist-row dash-loanlist-row--link';
      row.href = '/loans.html?id=' + encodeURIComponent(loan.id);
      row.setAttribute('aria-label',
        'View loan #' + (loan.publicId || loan.id || '')
      );

      var main = document.createElement('div');
      main.className = 'dash-loanlist-main';

      var top = document.createElement('div');
      top.className = 'dash-loanlist-top';

      var idEl = document.createElement('strong');
      idEl.textContent = 'Loan #' + (loan.publicId || loan.id || '—');
      top.appendChild(idEl);

      var pill = document.createElement('span');
      pill.className = 'dash-pill ' + statusPillClass(loan);
      pill.textContent = statusPillText(loan);
      top.appendChild(pill);

      var small = document.createElement('small');
      var dateStr = loan.loanDate || loan.originationDate;
      small.textContent = 'Originated ' + (dateStr ? fmtDate(dateStr) : '—');

      main.appendChild(top);
      main.appendChild(small);

      var right = document.createElement('div');
      right.className = 'dash-loanlist-amount';
      var label = document.createElement('small');
      label.textContent = loan.isOutstanding ? 'Balance' : 'Borrowed';
      var amt = document.createElement('strong');
      amt.textContent = fmtCurrency(loan.isOutstanding ? loan.balance : loan.principal);
      right.appendChild(label);
      right.appendChild(amt);

      var arrow = document.createElement('span');
      arrow.className = 'dash-loanlist-chevron';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

      row.appendChild(main);
      row.appendChild(right);
      row.appendChild(arrow);
      body.appendChild(row);
    });
  }

  function renderListError() {
    var body = qs('#loansListBody');
    if (!body) return;
    body.innerHTML =
      '<p class="dash-loanlist-empty">We couldn’t load your loans right now. Please refresh, or call us at <a href="tel:+17472707121">(747) 270-7121</a>.</p>';
  }

  function statusPillClass(loan) {
    var status = (loan.status || '').toLowerCase();
    var daysLate = (loan.daysLate || '').toLowerCase();
    if (!loan.isOutstanding) return 'dash-pill--closed';
    if (status.indexOf('past') !== -1 || status.indexOf('delinquent') !== -1 ||
        (daysLate && daysLate !== 'not late')) return 'dash-pill--past-due';
    if (status.indexOf('grace') !== -1 || status.indexOf('pending') !== -1 ||
        loan.isInRescindPeriod) return 'dash-pill--warn';
    return 'dash-pill--ok';
  }

  function statusPillText(loan) {
    var status = (loan.status || '').toLowerCase();
    var daysLate = (loan.daysLate || '').toLowerCase();
    if (!loan.isOutstanding) return loan.status || 'Closed';
    if (status.indexOf('past') !== -1 || status.indexOf('delinquent') !== -1 ||
        (daysLate && daysLate !== 'not late')) return 'Past due';
    if (loan.isInRescindPeriod) return 'Rescind period';
    return loan.status || 'Current';
  }

  // ---------- DETAIL VIEW ----------
  function showDetail(loanId) {
    qs('#loansListView').hidden = true;
    qs('#loansDetailView').hidden = false;
    setText(qs('#loansEyebrow'), 'Loan detail');
    setText(qs('#loansTitle'), 'Loan #' + loanId);
    setText(qs('#loansSubtitle'), 'Full loan details, payments, and documents.');

    api(ACTIVE_ENDPOINT, token)
      .then(function (data) {
        var loans = (data && data.allLoans) || [];
        var loan = loans.find(function (l) {
          return String(l.id) === String(loanId) ||
                 String(l.publicId || '') === String(loanId);
        });
        if (!loan) {
          renderDetailNotFound();
          return;
        }
        renderDetail(loan);
        loadDocuments(loan.id);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderDetailError();
      });
  }

  function renderDetail(loan) {
    setText(qs('#loansTitle'), 'Loan #' + (loan.publicId || loan.id));
    setText(qs('#loanDetailTitle'), 'Loan #' + (loan.publicId || loan.id));

    var meta = [];
    if (loan.loanClass) meta.push(loan.loanClass);
    if (loan.loanDate || loan.originationDate) {
      meta.push('Originated ' + fmtDate(loan.loanDate || loan.originationDate));
    }
    if (loan.storeName) meta.push(loan.storeName);
    setText(qs('#loanDetailMeta'), meta.join(' · ') || '—');

    var pill = qs('#loanDetailPill');
    if (pill) {
      pill.className = 'dash-pill ' + statusPillClass(loan);
      pill.textContent = statusPillText(loan);
    }

    var summary;
    if (loan.isOutstanding) {
      summary = [
        ['Status', loan.status || 'Current'],
        ['Amount Borrowed', fmtCurrency(loan.principal)],
        ['Current Balance', fmtCurrency(loan.balance)],
        ['Payoff Amount', fmtCurrency(loan.payoffAmount)],
        ['Next Payment', loan.nextDueDate
          ? fmtCurrency(loan.nextDueAmount) + ' on ' + fmtDate(loan.nextDueDate)
          : '—'],
        ['Payment Status', loan.daysLate || '—']
      ];
    } else {
      var principal = Number(loan.principal) || 0;
      var fees = Number(loan.fees) || 0;
      summary = [
        ['Status', loan.status || 'Closed'],
        ['Amount Borrowed', fmtCurrency(loan.principal)],
        ['Fee', fmtCurrency(loan.fees)],
        ['Total Paid', fmtCurrency(principal + fees)],
        ['Payment Status', loan.daysLate || '—']
      ];
    }
    renderStats(qs('#loanStatsSummary'), summary);
  }

  function renderStats(root, pairs) {
    if (!root) return;
    root.innerHTML = '';
    pairs.forEach(function (p) {
      var dt = document.createElement('dt');
      dt.textContent = p[0];
      var dd = document.createElement('dd');
      dd.textContent = p[1];
      root.appendChild(dt);
      root.appendChild(dd);
    });
  }

  // ---------- DOCUMENTS ----------
  function loadDocuments(loanId) {
    api(DOCS_ENDPOINT + '?loanId=' + encodeURIComponent(loanId), token)
      .then(function (data) {
        renderDocuments((data && data.documents) || []);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderDocumentsError();
      });
  }

  function renderDocuments(docs) {
    var root = qs('#loanDocuments');
    var count = qs('#loanDocsCount');
    if (!root) return;
    root.innerHTML = '';

    if (!docs.length) {
      var p = document.createElement('p');
      p.className = 'dash-loanlist-empty';
      p.textContent = 'No documents on file for this loan yet.';
      root.appendChild(p);
      if (count) count.hidden = true;
      return;
    }
    if (count) {
      count.textContent = docs.length + (docs.length === 1 ? ' document' : ' documents');
      count.hidden = false;
    }

    var list = document.createElement('div');
    list.className = 'dash-doc-list';

    docs.forEach(function (doc) {
      var row = document.createElement('div');
      row.className = 'dash-doc-row';
      row.setAttribute('role', 'button');
      row.setAttribute('tabindex', '0');
      row.setAttribute('aria-label', 'View ' + (doc.displayName || doc.fileName || 'document'));

      var icon = document.createElement('span');
      icon.className = 'dash-doc-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

      var meta = document.createElement('div');
      meta.className = 'dash-doc-meta';
      var title = document.createElement('strong');
      title.textContent = doc.displayName || doc.fileName || ('Document #' + doc.id);
      var sub = document.createElement('small');
      var subParts = [];
      if (doc.documentDate) subParts.push(fmtDate(doc.documentDate));
      if (doc.kind === 'other') subParts.push('Additional');
      sub.textContent = subParts.join(' · ') || '—';
      meta.appendChild(title);
      meta.appendChild(sub);

      var actions = document.createElement('div');
      actions.className = 'dash-doc-actions';

      var viewBtn = document.createElement('button');
      viewBtn.type = 'button';
      viewBtn.className = 'dash-doc-view';
      viewBtn.textContent = 'View';
      viewBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        openDocInModal(doc, viewBtn);
      });

      var dlBtn = document.createElement('button');
      dlBtn.type = 'button';
      dlBtn.className = 'dash-doc-download';
      dlBtn.textContent = 'Download';
      dlBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        downloadDocument(doc, dlBtn);
      });

      actions.appendChild(viewBtn);
      actions.appendChild(dlBtn);

      // Row click = default action (View). Buttons stopPropagation so
      // nothing fires twice.
      row.addEventListener('click', function () { openDocInModal(doc, viewBtn); });
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openDocInModal(doc, viewBtn);
        }
      });

      row.appendChild(icon);
      row.appendChild(meta);
      row.appendChild(actions);
      list.appendChild(row);
    });
    root.appendChild(list);
  }

  function renderDocumentsError() {
    var root = qs('#loanDocuments');
    if (!root) return;
    root.innerHTML =
      '<p class="dash-loanlist-empty">We couldn’t load documents right now. Please refresh, or call us at <a href="tel:+17472707121">(747) 270-7121</a>.</p>';
  }

  // ---------- DOCUMENT VIEWER (MODAL) + DOWNLOAD ----------
  var _activeBlobUrl = null;  // currently-displayed modal blob — revoked on close

  // format='html' for the modal viewer (Vergent's native HTML, fast),
  // 'pdf' for the Download button (rendered server-side via headless
  // Chromium so the customer gets a real PDF on disk).
  function fetchDocBlob(doc, format) {
    var url = DOCS_ENDPOINT + '/' + encodeURIComponent(doc.id) + '/download';
    if (format === 'pdf') url += '?format=pdf';
    return fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': '*/*' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL);
        throw new Error('unauthorized');
      }
      if (!res.ok) throw new Error('http ' + res.status);
      return res.blob();
    });
  }

  function pdfFileName(doc) {
    var n = doc.fileName || ('document-' + doc.id);
    // Strip .html / .aspx / .htm and append .pdf so the saved file is
    // labelled correctly when the customer opens their downloads folder.
    n = n.replace(/\.(html|htm|aspx)$/i, '');
    if (!/\.pdf$/i.test(n)) n += '.pdf';
    return n;
  }

  function openDocInModal(doc, btn) {
    var orig = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Opening…'; }
    // Modal uses the HTML render — it's fast (~200ms) and the iframe
    // renders Vergent's docs perfectly. The Download button inside
    // the modal triggers the PDF render path separately.
    fetchDocBlob(doc, 'html').then(function (blob) {
      // Release any previous blob URL still attached to the modal.
      if (_activeBlobUrl) { URL.revokeObjectURL(_activeBlobUrl); _activeBlobUrl = null; }
      var url = URL.createObjectURL(blob);
      _activeBlobUrl = url;

      setText(qs('#docModalTitle'), doc.displayName || doc.fileName || 'Document');
      var dl = qs('#docModalDownload');
      if (dl) {
        // Wire the modal's Download button to trigger the same PDF
        // download path the row-level Download button uses (not the
        // HTML blob URL — that'd save .html which is what we're
        // moving away from).
        dl.onclick = function (e) {
          e.preventDefault();
          downloadDocument(doc, dl);
        };
        dl.removeAttribute('href');
        dl.removeAttribute('download');
      }

      var loading = qs('#docModalLoading');
      var frame = qs('#docModalFrame');
      if (loading) loading.hidden = false;
      if (frame) {
        // The iframe stays visible (the loading panel sits on top via
        // z-index until onload fires). Setting display:none / hidden
        // prevents Chrome from firing onload and stalls the spinner.
        frame.onload = function () {
          if (loading) loading.hidden = true;
        };
        frame.src = url;
      }
      // Watchdog — if onload doesn't fire (some Vergent docs reference
      // external CSS that fails to fetch from a blob: origin), hide
      // the loading panel after 6s so the user sees what did render.
      setTimeout(function () {
        if (loading && !loading.hidden) loading.hidden = true;
      }, 6000);

      qs('#docModal').hidden = false;
      document.body.style.overflow = 'hidden';

      if (btn) { btn.disabled = false; btn.textContent = orig; }
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      if (btn) { btn.disabled = false; btn.textContent = orig; }
      alert('Sorry — we couldn’t open that document right now. Please try again, or call (747) 270-7121.');
    });
  }

  function closeDocModal() {
    var modal = qs('#docModal');
    if (!modal || modal.hidden) return;
    var frame = qs('#docModalFrame');
    if (frame) {
      frame.onload = null;
      frame.src = 'about:blank';
    }
    var loading = qs('#docModalLoading');
    if (loading) loading.hidden = true;
    var dl = qs('#docModalDownload');
    if (dl) {
      dl.removeAttribute('href');
      dl.removeAttribute('download');
      dl.onclick = null;
    }
    if (_activeBlobUrl) {
      // Slight delay so the iframe finishes releasing the URL.
      var u = _activeBlobUrl;
      _activeBlobUrl = null;
      setTimeout(function () { URL.revokeObjectURL(u); }, 500);
    }
    modal.hidden = true;
    document.body.style.overflow = '';
  }

  function initDocModal() {
    var modal = qs('#docModal');
    if (!modal) return;
    // Close-control clicks (backdrop, X, anything with data-action="doc-close").
    modal.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t !== modal) {
        if (t.getAttribute && t.getAttribute('data-action') === 'doc-close') {
          closeDocModal();
          return;
        }
        t = t.parentNode;
      }
    });
    // ESC key.
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) closeDocModal();
    });
  }

  function downloadDocument(doc, btn) {
    var orig = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Preparing PDF…'; }
    // Server-side PDF render via the doc-pdf Lambda (headless Chromium).
    // First-call cold-start can be ~5–8s; warm calls are 1–3s.
    fetchDocBlob(doc, 'pdf').then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = pdfFileName(doc);
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      if (btn) { btn.disabled = false; btn.textContent = orig; }
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      if (btn) { btn.disabled = false; btn.textContent = orig; }
      alert('Sorry — we couldn’t download that document right now. Please try again, or call (747) 270-7121.');
    });
  }

  function renderDetailNotFound() {
    var v = qs('#loansDetailView');
    if (v) {
      v.innerHTML =
        '<a href="/loans.html" class="dash-back-link">' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg> All loans</a>' +
        '<section class="dash-card"><div class="dash-card-head"><h3>Loan not found</h3></div>' +
        '<p style="color:#555;">We couldn’t find a loan with that ID on your account. ' +
        '<a href="/loans.html" style="color:#0E8741; font-weight:600;">Back to all loans</a>.</p></section>';
    }
  }

  function renderDetailError() {
    var v = qs('#loansDetailView');
    if (v) {
      v.innerHTML =
        '<a href="/loans.html" class="dash-back-link">' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg> All loans</a>' +
        '<section class="dash-card"><div class="dash-card-head"><h3>Couldn’t load loan</h3></div>' +
        '<p style="color:#555;">Please refresh, or call us at <a href="tel:+17472707121" style="color:#0E8741;">(747) 270-7121</a>.</p></section>';
    }
  }
})();
