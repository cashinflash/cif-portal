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
  var ACTIVITY_ENDPOINT = API_BASE + '/my-loans/activity';
  var DOCS_ENDPOINT = API_BASE + '/my-loans/documents';
  var LOGIN_URL = '/start.html';
  var ACTIVITY_LIMIT = 50;

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
        loadActivity(loan.id);
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

    renderStats(qs('#loanStatsSummary'), [
      ['Status', loan.status || (loan.isOutstanding ? 'Current' : 'Closed')],
      ['Original principal', fmtCurrency(loan.principal)],
      [loan.isOutstanding ? 'Current balance' : 'Final balance', fmtCurrency(loan.balance)],
      ['Payoff amount', fmtCurrency(loan.payoffAmount)],
      ['Next payment', loan.isOutstanding && loan.nextDueDate
        ? fmtCurrency(loan.nextDueAmount) + ' on ' + fmtDate(loan.nextDueDate)
        : '—'],
      ['Days late', loan.daysLate || '—']
    ]);

    renderStats(qs('#loanStatsDetails'), [
      ['Loan ID', String(loan.publicId || loan.id || '—')],
      ['APR', fmtApr(loan.apr)],
      ['Origination date', fmtDate(loan.loanDate || loan.originationDate)],
      ['Number of payments', loan.numberOfPayments != null ? String(loan.numberOfPayments) : '—'],
      ['Fees', fmtCurrency(loan.fees)],
      ['Fee balance', fmtCurrency(loan.feeBalance)],
      ['Store', loan.storeName || '—'],
      ['Eligible for refinance', fmtBool(loan.isEligibleForRefi)],
      ['In rescind period', fmtBool(loan.isInRescindPeriod)],
      ['Autopay scheduled', fmtBool(loan.autopay)]
    ]);
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

  function loadActivity(loanId) {
    api(ACTIVITY_ENDPOINT + '?loanId=' + encodeURIComponent(loanId) +
        '&limit=' + ACTIVITY_LIMIT, token)
      .then(function (data) {
        renderActivity((data && data.items) || []);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderActivityError();
      });
  }

  function renderActivity(items) {
    var root = qs('#loanActivity');
    if (!root) return;
    root.innerHTML = '';

    if (!items.length) {
      var p = document.createElement('p');
      p.className = 'dash-loanlist-empty';
      p.textContent = 'No transactions on this loan yet.';
      root.appendChild(p);
      return;
    }

    var table = document.createElement('div');
    table.className = 'dash-activity-table';

    items.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'dash-activity-row';

      var when = document.createElement('div');
      when.className = 'dash-activity-when';
      when.textContent = fmtDate(item.date);

      var desc = document.createElement('div');
      desc.className = 'dash-activity-desc';
      desc.textContent = item.description || 'Activity';

      var amt = document.createElement('div');
      amt.className = 'dash-activity-amt ' +
        (item.direction === 'credit' ? 'is-credit' : 'is-debit');
      var prefix = item.direction === 'credit' ? '−' : '+';
      amt.textContent = item.amount != null
        ? (prefix + fmtCurrency(item.amount).replace(/^-/, ''))
        : '—';

      var bal = document.createElement('div');
      bal.className = 'dash-activity-bal';
      bal.textContent = item.balance != null
        ? 'Balance ' + fmtCurrency(item.balance) : '';

      row.appendChild(when);
      row.appendChild(desc);
      row.appendChild(amt);
      row.appendChild(bal);
      table.appendChild(row);
    });
    root.appendChild(table);
  }

  function renderActivityError() {
    var root = qs('#loanActivity');
    if (!root) return;
    root.innerHTML =
      '<p class="dash-loanlist-empty">We couldn’t load transactions right now.</p>';
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

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dash-doc-view';
      btn.textContent = 'View';
      btn.addEventListener('click', function () { openDocument(doc, btn); });

      row.appendChild(icon);
      row.appendChild(meta);
      row.appendChild(btn);
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

  function openDocument(doc, btn) {
    var orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Opening…';
    fetch(DOCS_ENDPOINT + '/' + encodeURIComponent(doc.id) + '/download', {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': '*/*' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL);
        throw new Error('unauthorized');
      }
      if (!res.ok) {
        throw new Error('http ' + res.status);
      }
      return res.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var w = window.open(url, '_blank', 'noopener,noreferrer');
      if (!w) {
        // Pop-up blocked — fall back to a one-shot anchor click.
        var a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.download = doc.fileName || ('document-' + doc.id + '.pdf');
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
      // Revoke the blob URL after a delay so the new tab has time to load.
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
      btn.disabled = false;
      btn.textContent = orig;
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      btn.disabled = false;
      btn.textContent = orig;
      alert('Sorry — we couldn’t open that document right now. Please try again, or call (747) 270-7121.');
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
