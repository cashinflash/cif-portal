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
        window.location.replace(LOGIN_URL + '?reason=session_expired');
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
    window.location.replace(LOGIN_URL + '?reason=session_expired');
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
    var esignParam = params.get('esign');
    var actionParam = params.get('action');

    // Backwards-compat: older dashboard banner deep-linked here
    // with ?esign=<guid>&action=sign. Redirect such links straight
    // to Vergent's hosted signing page so stale bookmarks still
    // work after the simplification.
    if (esignParam && actionParam === 'sign') {
      window.location.replace('https://shared.vergentlms.com/esign?g=' +
                              encodeURIComponent(esignParam));
      return;
    }

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
    var heroPill = qs('#loanDetailPillHero');
    if (heroPill) heroPill.hidden = true;

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
        // Documents section is shown for both active and paid-off
        // loans. Active loans have origination docs (Advance
        // Contract, DDT Disclosure, Advance Receipt at funding);
        // paid-off loans add payment receipts, one per payment.
        var docsSection = qs('#loanDocumentsSection');
        if (docsSection) docsSection.style.display = '';
        loadDocuments(loan.id);
        loadPendingEsignFor(loan.id);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderDetailError();
      });
  }

  function renderDetail(loan) {
    setText(qs('#loansTitle'), 'Loan #' + (loan.publicId || loan.id));

    var pill = qs('#loanDetailPillHero');
    if (pill) {
      pill.className = 'dash-pill dash-hero-pill ' + statusPillClass(loan);
      pill.textContent = statusPillText(loan);
      pill.hidden = false;
    }

    // Unified Summary for both active and paid-off loans:
    // Originated / Status / Amount Borrowed / Fee / Total Paid / Payment Status.
    // Total Paid is always (principal + fees) - current_balance,
    // which:
    //   - Equals (principal + fees) for a paid-off loan (balance = 0).
    //   - Equals 0 (or partial) for an active loan with payments
    //     not yet made (balance still high).
    var principal = Number(loan.principal) || 0;
    var fees = Number(loan.fees) || 0;
    var balance = Number(loan.balance) || 0;
    var totalDue = principal + fees;
    var totalPaid = Math.max(0, totalDue - balance);
    // Summary card splits into two columns:
    //   Left: lifecycle / status (Originated, Due Date, Status, Payment Status)
    //   Right: money (Amount Borrowed, Fee, Total Paid)
    // Stacks to a single column on mobile via the .dash-loan-stats-pair
    // grid breakpoint.
    var originatedRaw = loan.loanDate || loan.originationDate;
    var leftSummary = [
      ['Originated', originatedRaw ? fmtDate(originatedRaw) : '—'],
      ['Due Date', loan.nextDueDate ? fmtDate(loan.nextDueDate) : '—'],
      ['Status', loan.status || (loan.isOutstanding ? 'Current' : 'Closed')],
      ['Payment Status', loan.daysLate || '—'],
    ];
    var rightSummary = [
      ['Amount Borrowed', fmtCurrency(principal)],
      ['Fee', fmtCurrency(fees)],
      ['Total Paid', fmtCurrency(totalPaid)],
    ];
    renderStats(qs('#loanStatsSummaryLeft'), leftSummary);
    renderStats(qs('#loanStatsSummaryRight'), rightSummary);
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

  // ---------- E-sign per-loan callout ----------
  // If THIS loan has at least one pending e-sign, render a slim
  // amber callout above the Documents card with a "Send me the
  // link" button. Same backend endpoints the dashboard banner
  // uses; filtered to entries whose loanId / publicLoanId matches.
  function loadPendingEsignFor(loanId) {
    var callout = qs('#loanEsignCallout');
    if (!callout) return;
    callout.hidden = true;
    api('/api/my-esign/pending', token)
      .then(function (data) {
        var pending = (data && data.pending) || [];
        var match = pending.filter(function (p) {
          return String(p.loanId) === String(loanId)
              || String(p.publicLoanId) === String(loanId);
        });
        if (match.length) {
          var first = match[0] || {};
          var fallback = first.id
            ? ('https://shared.vergentlms.com/esign?g=' + encodeURIComponent(first.id))
            : '#';
          renderEsignCallout(callout, loanId,
                             first.signingUrl || fallback, match.length);
        }
      })
      .catch(function () { /* silent */ });
  }

  function renderEsignCallout(root, loanId, signHref, count) {
    var noun = count > 1 ? (count + ' documents') : '1 document';
    root.innerHTML = (
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
      '<polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/></svg>' +
      '<div class="dash-esign-callout-text">' +
      '  <strong>This loan has ' + noun + ' waiting for your signature.</strong>' +
      '  <p>Click Sign now to e-sign on Vergent’s secure page in a new tab.</p>' +
      '</div>' +
      '<div class="dash-esign-callout-actions">' +
      '  <a class="dash-esign-callout-btn dash-esign-callout-btn--primary" href="' + signHref + '" target="_blank" rel="noopener">Sign now</a>' +
      '  <button type="button" class="dash-esign-callout-btn" data-action="esign-resend">Send me the link</button>' +
      '</div>'
    );
    root.hidden = false;
    var resendBtn = qs('[data-action="esign-resend"]', root);
    if (resendBtn) {
      resendBtn.addEventListener('click', function () {
        resendBtn.disabled = true;
        resendBtn.textContent = 'Sending…';
        fetch('/api/my-esign/resend', {
          method: 'POST',
          headers: {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          credentials: 'omit',
          body: JSON.stringify({ loanId: loanId }),
        }).then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (data && data.ok) {
              resendBtn.textContent = 'Email sent ✓';
            } else {
              resendBtn.textContent = 'Try again';
              resendBtn.disabled = false;
            }
          }).catch(function () {
            resendBtn.textContent = 'Try again';
            resendBtn.disabled = false;
          });
      });
    }
  }

  // ---------- E-sign modal: in-portal signing ceremony ----------
  // Fetches the unsigned doc set from /api/my-esign/document, lets
  // the customer type their name + check the consent box, then
  // POSTs to /api/my-esign/sign which forwards to Vergent's
  // signingdata endpoint. Reuses the doc-modal CSS pattern.
  // Open the e-sign modal using the esign GUID directly (no
  // loanId needed). Called from the dashboard "Sign now" deep
  // link: /loans.html?esign=<guid>&action=sign.
  function openEsignModalByGuid(esignId) {
    openEsignModalCore({ esignId: esignId });
  }

  function openEsignModal(loanId) {
    openEsignModalCore({ loanId: loanId });
  }

  function openEsignModalCore(target) {
    var modal = qs('#esignModal');
    if (!modal) return;
    var body = qs('#esignModalBody');
    var loading = qs('#esignModalLoading');
    var foot = qs('#esignModalFoot');
    var errorEl = qs('#esignModalError');
    var nameEl = qs('#esignSignerName');
    var agreeEl = qs('#esignAgreeBox');
    var submitBtn = qs('#esignSubmitBtn');

    // Reset state
    if (errorEl) { errorEl.hidden = true; errorEl.textContent = ''; }
    if (nameEl) nameEl.value = '';
    if (agreeEl) agreeEl.checked = false;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sign now';
    }
    if (foot) foot.hidden = true;
    if (loading) loading.hidden = false;
    if (body) {
      // Strip any previous render but keep the loading element.
      body.innerHTML = '';
      var p = document.createElement('p');
      p.className = 'dash-loading';
      p.id = 'esignModalLoading';
      p.textContent = 'Loading document…';
      body.appendChild(p);
    }

    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    var docUrl = '/api/my-esign/document';
    if (target.esignId) {
      docUrl += '?esignId=' + encodeURIComponent(target.esignId);
    } else if (target.loanId) {
      docUrl += '?loanId=' + encodeURIComponent(target.loanId);
    }

    fetch(docUrl, {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      credentials: 'omit',
    }).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
        throw new Error('unauthorized');
      }
      if (!r.ok) return r.json().then(function (e) { throw new Error(e && e.error || 'http ' + r.status); });
      return r.json();
    }).then(function (data) {
      renderEsignDocument(data && data.document);
      if (qs('#esignModalFoot')) qs('#esignModalFoot').hidden = false;
      if (qs('#esignModalLoading')) qs('#esignModalLoading').hidden = true;
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      var b = qs('#esignModalBody');
      if (b) {
        b.innerHTML = '<p class="dash-esign-error" style="display:block">' +
          'We couldn’t load this document. Please refresh, or call (747) 270-7121.</p>';
      }
    });

    wireEsignSubmit(target);
  }

  function renderEsignDocument(doc) {
    var body = qs('#esignModalBody');
    if (!body) return;
    body.innerHTML = '';
    if (doc == null) {
      body.textContent = 'No document content received.';
      return;
    }
    // Vergent's response shape isn't documented — handle the
    // common cases. If a string, it's likely HTML; if an object
    // with a Data / Content / DocumentContent field, render that.
    var html = null;
    if (typeof doc === 'string') {
      html = doc;
    } else if (typeof doc === 'object') {
      html = doc.Data || doc.data || doc.Content || doc.content
          || doc.DocumentContent || doc.documentContent
          || doc.Html || doc.html;
      if (!html && Array.isArray(doc.Documents || doc.documents)) {
        var docs = doc.Documents || doc.documents;
        html = docs.map(function (d) {
          return d && (d.Data || d.Content || d.Html || '');
        }).filter(Boolean).join('<hr>');
      }
    }
    if (html && /^[A-Za-z0-9+/=]+$/.test(html.trim()) && html.length > 200) {
      // Likely base64-encoded — decode and render.
      try {
        html = decodeURIComponent(escape(atob(html)));
      } catch (e) { /* not base64 — leave as-is */ }
    }
    if (html) {
      var iframe = document.createElement('iframe');
      iframe.className = 'dash-esign-doc-frame';
      iframe.title = 'Loan documents';
      iframe.srcdoc = html;
      body.appendChild(iframe);
    } else {
      // Fall back to JSON dump so we can see what Vergent gave us.
      var pre = document.createElement('pre');
      pre.className = 'dash-esign-doc-json';
      pre.textContent = JSON.stringify(doc, null, 2);
      body.appendChild(pre);
    }
  }

  function wireEsignSubmit(target) {
    var nameEl = qs('#esignSignerName');
    var agreeEl = qs('#esignAgreeBox');
    var submitBtn = qs('#esignSubmitBtn');
    var errorEl = qs('#esignModalError');
    if (!nameEl || !agreeEl || !submitBtn) return;

    function refreshSubmitState() {
      submitBtn.disabled = !(nameEl.value.trim() && agreeEl.checked);
    }
    nameEl.oninput = refreshSubmitState;
    agreeEl.onchange = refreshSubmitState;

    submitBtn.onclick = function () {
      var name = nameEl.value.trim();
      if (!name || !agreeEl.checked) return;
      submitBtn.disabled = true;
      submitBtn.textContent = 'Signing…';
      if (errorEl) { errorEl.hidden = true; errorEl.textContent = ''; }
      var bodyPayload = { signerName: name, agreed: true };
      if (target && target.esignId) bodyPayload.esignId = target.esignId;
      else if (target && target.loanId) bodyPayload.loanId = target.loanId;
      fetch('/api/my-esign/sign', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        credentials: 'omit',
        body: JSON.stringify(bodyPayload),
      }).then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      }).then(function (res) {
        if (res.ok && res.data && res.data.ok) {
          submitBtn.textContent = 'Signed ✓';
          var body = qs('#esignModalBody');
          if (body) {
            body.innerHTML = '<div class="dash-esign-done">' +
              '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>' +
              '<h4>Thank you, ' + name.split(' ')[0] + '!</h4>' +
              '<p>Your signature has been recorded. Your loan documents will be available in the Documents section once finalized.</p>' +
              '<button type="button" class="dash-esign-submit" data-action="esign-close">Done</button>' +
              '</div>';
          }
          var foot = qs('#esignModalFoot');
          if (foot) foot.hidden = true;
          // Clear the callout — it'll re-render empty on reload.
          var callout = qs('#loanEsignCallout');
          if (callout) callout.hidden = true;
        } else {
          submitBtn.textContent = 'Sign now';
          submitBtn.disabled = false;
          if (errorEl) {
            var msg = 'Sorry — we couldn’t complete the signature. Please try again, or call us at (747) 270-7121.';
            if (res.data && res.data.upstreamStatus) {
              msg += ' (Vergent ' + res.data.upstreamStatus + ')';
            }
            errorEl.textContent = msg;
            errorEl.hidden = false;
          }
        }
      }).catch(function () {
        submitBtn.textContent = 'Sign now';
        submitBtn.disabled = false;
        if (errorEl) {
          errorEl.textContent = 'Network error. Please try again.';
          errorEl.hidden = false;
        }
      });
    };
  }

  function closeEsignModal() {
    var modal = qs('#esignModal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.style.overflow = '';
  }

  function initEsignModal() {
    var modal = qs('#esignModal');
    if (!modal) return;
    modal.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t !== modal) {
        if (t.getAttribute && t.getAttribute('data-action') === 'esign-close') {
          closeEsignModal();
          return;
        }
        t = t.parentNode;
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) closeEsignModal();
    });
  }
  initEsignModal();

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
  // format='html' for the modal viewer (Vergent's native HTML, fast),
  // 'pdf' for the Download button (rendered server-side via headless
  // Chromium so the customer gets a real PDF on disk).
  function fetchDocBlob(doc, format) {
    var url = DOCS_ENDPOINT + '/' + encodeURIComponent(doc.id) + '/download';
    var qs = [];
    if (format === 'pdf') qs.push('format=pdf');
    if (doc.loanId) qs.push('loanId=' + encodeURIComponent(doc.loanId));
    if (qs.length) url += '?' + qs.join('&');
    return fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': '*/*' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
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
    // Modal renders the doc via iframe srcdoc (inline HTML) instead of
    // a blob: URL. iOS Safari is unreliable with blob: URLs in iframes
    // — produces blank white renders. srcdoc handles inline HTML
    // consistently across desktop + mobile browsers. Bonus: no blob
    // URL lifecycle to manage for the modal (download still uses one).
    var url = DOCS_ENDPOINT + '/' + encodeURIComponent(doc.id) + '/download';
    if (doc.loanId) url += '?loanId=' + encodeURIComponent(doc.loanId);
    fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': '*/*' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
        throw new Error('unauthorized');
      }
      if (!res.ok) throw new Error('http ' + res.status);
      return res.text();
    }).then(function (html) {
      setText(qs('#docModalTitle'), doc.displayName || doc.fileName || 'Document');
      var dl = qs('#docModalDownload');
      if (dl) {
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

      // Show the modal first so the iframe is in a visible layout when
      // its content loads.
      qs('#docModal').hidden = false;
      document.body.style.overflow = 'hidden';

      if (frame) {
        frame.onload = function () {
          if (loading) loading.hidden = true;
        };
        // srcdoc replaces src for inline HTML rendering. Vergent's docs
        // reference external CSS at shared.vergentlms.com which may or
        // may not load (CORS), but the document body always renders.
        frame.removeAttribute('src');
        frame.srcdoc = html;
      }
      // Watchdog — if onload doesn't fire, hide loading after 6s.
      setTimeout(function () {
        if (loading && !loading.hidden) loading.hidden = true;
      }, 6000);

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
      // Clear srcdoc so the iframe doesn't keep the doc HTML in memory
      // while the modal is closed. about:blank for src as belt+suspenders.
      frame.removeAttribute('srcdoc');
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

  function _triggerDownload(blob, fileName) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
  }

  function downloadDocument(doc, btn) {
    var orig = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Preparing PDF…'; }
    // Try server-side PDF render first (doc-pdf Lambda). If it fails
    // (function not yet deployed, render error, etc.), fall back to
    // saving Vergent's original HTML — the customer always gets SOMETHING
    // rather than a broken file.
    fetchDocBlob(doc, 'pdf').then(function (blob) {
      _triggerDownload(blob, pdfFileName(doc));
      if (btn) { btn.disabled = false; btn.textContent = orig; }
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      // PDF path failed — fall back to HTML so the user gets a valid
      // file with the correct extension. They can still print-to-PDF
      // from the browser if they want PDF specifically.
      console.warn('[loans] PDF render failed, falling back to HTML', err);
      if (btn) btn.textContent = 'Downloading…';
      fetchDocBlob(doc, 'html').then(function (blob) {
        var fname = doc.fileName || ('document-' + doc.id + '.html');
        _triggerDownload(blob, fname);
        if (btn) { btn.disabled = false; btn.textContent = orig; }
      }).catch(function (err2) {
        if (err2 && err2.message === 'unauthorized') return;
        if (btn) { btn.disabled = false; btn.textContent = orig; }
        alert('Sorry — we couldn’t download that document right now. Please try again, or call (747) 270-7121.');
      });
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
