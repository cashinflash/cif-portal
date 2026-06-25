/* ═══════════════════════════════════════════════════════════════════
   CASH IN FLASH — shared e-sign helpers (window.CifEsign)

   Loaded on dashboard, loans, payments, profile so a loan that's waiting
   on the customer's signature is treated IDENTICALLY portal-wide:
     • the active-loan card shows an "Awaiting signature" state (never a
       healthy "Current" card for an unsigned, unfunded loan),
     • a prompt strip with a "Review & sign" button appears on every page,
     • the payments form is blocked (you can't pay a loan that isn't funded),
     • a beautiful in-portal modal lets them review the documents and sign,
     • the moment Vergent clears it from the e-sign queue (i.e. they signed)
       the portal flips to the normal active-loan card — no 15-minute wait
       on the slower Pending→Held customer-status change.

   Detection is authoritative from the backend: /api/my-loans/active flags
   `pendingSignature` + an `esign` handle (id + hosted signingUrl) when the
   outstanding loan is unfunded AND present in Vergent's /esign/pending queue.
   We also expose a list matcher so pages that don't carry the flag can match
   by loanId against /api/my-esign/pending directly.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var TTL = 20000;            // pending-list cache (ms)
  var _cache = null, _cacheAt = 0, _inflight = null;
  var _current = null;        // esign handle currently surfaced (for the open button)
  var _hadPending = false;    // we showed a "sign" state this load → watch for the flip

  function token() { try { return sessionStorage.getItem('cif_id_token'); } catch (e) { return null; } }

  // Customer's name from the ID token, so signing needs no typing.
  function _signerName() {
    try {
      var t = token(); if (!t) return '';
      var seg = t.split('.')[1]; if (!seg) return '';
      var p = JSON.parse(decodeURIComponent(escape(atob(seg.replace(/-/g, '+').replace(/_/g, '/')))));
      return (p.name || ((p.given_name || '') + ' ' + (p.family_name || '')).trim() || p.given_name || '').trim();
    } catch (e) { return ''; }
  }

  // GET /api/my-esign/pending (cached). Resolves to an array (never rejects).
  function fetchPending(force) {
    var now = Date.now();
    if (!force && _cache && (now - _cacheAt) < TTL) return Promise.resolve(_cache);
    if (_inflight) return _inflight;
    var t = token();
    if (!t) return Promise.resolve([]);
    _inflight = fetch('/api/my-esign/pending', {
      headers: { 'Authorization': 'Bearer ' + t, 'Accept': 'application/json' },
      credentials: 'omit'
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { _cache = (d && d.pending) || []; _cacheAt = Date.now(); _inflight = null; return _cache; })
      .catch(function () { _inflight = null; return _cache || []; });
    return _inflight;
  }

  // The esign handle for a loan, preferring the backend flag on the loan
  // object, falling back to a match against a supplied pending list.
  // Returns { id, signingUrl, documentName, loanId } or null.
  function infoForLoan(loan, list) {
    if (!loan) return null;
    if ((loan.pendingSignature || loan.lifecycle === 'pending_signature') && loan.esign) {
      return {
        id: loan.esign.id, signingUrl: loan.esign.signingUrl,
        documentName: loan.esign.documentName, loanId: loan.id
      };
    }
    if (list && list.length) {
      for (var i = 0; i < list.length; i++) {
        var p = list[i];
        if (String(p.loanId) === String(loan.id) ||
            (p.publicLoanId && loan.publicId && String(p.publicLoanId) === String(loan.publicId))) {
          return { id: p.id, signingUrl: p.signingUrl, documentName: p.documentName, loanId: p.loanId };
        }
      }
    }
    return null;
  }
  function isPending(loan) { return !!infoForLoan(loan); }

  // Consistent status pill on the active-loan card while unsigned.
  function applyPill(pill) {
    if (!pill) return;
    pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due',
      'dash-pill--closed', 'pay-pill--pending', 'cif-pill-processing', 'cif-pill-returned');
    pill.classList.add('cif-pill-sign');
    pill.textContent = 'Awaiting signature';
  }

  function _stripHtml() {
    return '<span class="cif-esign-ico" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/></svg></span>' +
      '<span class="cif-esign-strip-text"><strong>Your loan agreement is ready to sign</strong><small>Sign it to receive your funds — it only takes a minute.</small></span>' +
      '<button type="button" class="cif-esign-cta" data-esign-open>Review &amp; sign</button>';
  }
  // Fill every [data-esign-slot] anchor (or hide them when not pending).
  function renderStrip(esign) {
    _current = esign || _current;
    var slots = document.querySelectorAll('[data-esign-slot]');
    for (var i = 0; i < slots.length; i++) {
      var s = slots[i];
      if (!esign) { s.hidden = true; s.innerHTML = ''; s.classList.remove('cif-esign-strip'); continue; }
      if (!s.classList.contains('cif-esign-strip')) s.classList.add('cif-esign-strip');
      s.innerHTML = _stripHtml();
      s.hidden = false;
    }
    if (esign) _hadPending = true;
  }

  // ── In-portal signing modal (injected once, available on every page) ──
  var _modal = null;
  function _modalEl() {
    if (_modal) return _modal;
    var wrap = document.createElement('div');
    wrap.className = 'cif-esign-modal';
    wrap.hidden = true;
    wrap.innerHTML =
      '<button type="button" class="cif-esign-backdrop" data-esign-close aria-label="Close"></button>' +
      '<div class="cif-esign-card" role="dialog" aria-modal="true" aria-labelledby="cifEsignTitle">' +
        '<header class="cif-esign-head">' +
          '<h3 id="cifEsignTitle">Review &amp; sign your loan agreement</h3>' +
          '<button type="button" class="cif-esign-x" data-esign-close aria-label="Close">' +
            '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
          '</button>' +
        '</header>' +
        '<div class="cif-esign-body" data-esign-body>' +
          '<p class="cif-esign-loading" data-esign-loading>Loading your documents…</p>' +
        '</div>' +
        '<footer class="cif-esign-foot" data-esign-foot hidden>' +
          '<p class="cif-esign-legal">By tapping <strong>Sign &amp; Accept</strong>, I agree to and electronically sign the documents above. My electronic signature is legally binding.</p>' +
          '<p class="cif-esign-error" data-esign-error hidden></p>' +
          '<div class="cif-esign-actions">' +
            '<button type="button" class="cif-esign-cancel" data-esign-close>Cancel</button>' +
            '<button type="button" class="cif-esign-submit" data-esign-submit>Sign &amp; Accept</button>' +
          '</div>' +
          '<a class="cif-esign-alt" data-esign-hosted href="#" target="_blank" rel="noopener" hidden>Open the secure signing page &rarr;</a>' +
        '</footer>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t !== wrap) {
        if (t.getAttribute && t.getAttribute('data-esign-close') !== null) { hideModal(); return; }
        t = t.parentNode;
      }
    });
    _modal = wrap;
    return wrap;
  }

  function _decodeDoc(doc) {
    // Returns an array of { name, html } for rendering. Handles Vergent's
    // shape: { Documents: [{ DocumentName, Data(base64 html) }] } or a bare
    // string / single object. Mirrors loans.js renderEsignDocument decoding.
    function decode(html) {
      if (html && /^[A-Za-z0-9+/=\s]+$/.test(String(html).trim()) && String(html).length > 200) {
        try { return decodeURIComponent(escape(atob(String(html).replace(/\s+/g, '')))); } catch (e) { /* not base64 */ }
      }
      return html;
    }
    if (doc == null) return [];
    if (typeof doc === 'string') return [{ name: '', html: decode(doc) }];
    var list = doc.Documents || doc.documents;
    if (Array.isArray(list) && list.length) {
      return list.map(function (d) {
        return { name: (d && (d.DocumentName || d.documentName) || '').replace(/\.html?$/i, ''),
                 html: decode(d && (d.Data || d.Content || d.Html || '')) };
      }).filter(function (d) { return d.html; });
    }
    var single = doc.Data || doc.data || doc.Content || doc.content || doc.Html || doc.html;
    if (single) return [{ name: '', html: decode(single) }];
    return [];
  }

  function _renderDocs(bodyEl, doc) {
    var docs = _decodeDoc(doc);
    bodyEl.innerHTML = '';
    if (!docs.length) {
      bodyEl.innerHTML = '<p class="cif-esign-error" style="display:block">We couldn’t load your documents here. Please use the secure signing page below, or call (888) 999-9859.</p>';
      return;
    }
    docs.forEach(function (d) {
      if (d.name) {
        var h = document.createElement('div');
        h.className = 'cif-esign-doc-name';
        h.textContent = d.name;
        bodyEl.appendChild(h);
      }
      var f = document.createElement('iframe');
      f.className = 'cif-esign-doc-frame';
      f.title = d.name || 'Loan document';
      f.setAttribute('sandbox', 'allow-same-origin');
      f.srcdoc = d.html;
      bodyEl.appendChild(f);
    });
  }

  function _success(name) {
    var m = _modalEl();
    var body = m.querySelector('[data-esign-body]');
    var foot = m.querySelector('[data-esign-foot]');
    if (foot) foot.hidden = true;
    if (body) {
      body.innerHTML = '<div class="cif-esign-done">' +
        '<svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>' +
        '<h4>You’re all set' + (name ? (', ' + name.split(' ')[0]) : '') + '!</h4>' +
        '<p>Your agreement is signed. We’re activating your loan now — this page will refresh in a moment.</p>' +
        '</div>';
    }
    // Flip the whole portal to the now-active loan.
    setTimeout(function () { try { window.location.reload(); } catch (e) { /* ignore */ } }, 1900);
  }

  function _wireSubmit(esign) {
    var m = _modalEl();
    var submit = m.querySelector('[data-esign-submit]');
    var errEl = m.querySelector('[data-esign-error]');
    var hosted = m.querySelector('[data-esign-hosted]');
    if (hosted && esign && esign.signingUrl) hosted.href = esign.signingUrl;
    submit.textContent = 'Sign & Accept';
    submit.disabled = false;

    submit.onclick = function () {
      submit.disabled = true;
      submit.textContent = 'Signing…';
      if (errEl) { errEl.hidden = true; errEl.textContent = ''; errEl.classList.remove('cif-esign-info'); }
      var payload = { signerName: _signerName(), agreed: true };
      if (esign && esign.id) payload.esignId = esign.id;
      else if (esign && esign.loanId) payload.loanId = esign.loanId;
      fetch('/api/my-esign/sign', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'omit',
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; }).catch(function () { return { ok: r.ok, data: null }; });
      }).then(function (res) {
        if (res.ok && res.data && res.data.ok) { _success(_signerName()); return; }
        _handoff(esign, submit, errEl, hosted);
      }).catch(function () { _handoff(esign, submit, errEl, hosted); });
    };
  }

  // If in-portal signing can't complete, hand off to Vergent's secure hosted
  // signing page (new tab). The focus re-check flips the portal to the active
  // card once they finish there.
  function _handoff(esign, submit, errEl, hosted) {
    if (esign && esign.signingUrl) {
      try { window.open(esign.signingUrl, '_blank', 'noopener'); } catch (e) { /* popup blocked */ }
      if (hosted) hosted.hidden = false;
      if (errEl) {
        errEl.innerHTML = 'Opening our secure signing page in a new tab — finish there, then come back. This page updates automatically once you’re done.';
        errEl.classList.add('cif-esign-info');
        errEl.hidden = false;
      }
    } else if (errEl) {
      errEl.textContent = 'Something went wrong. Please try again, or call (888) 999-9859.';
      errEl.hidden = false;
    }
    if (submit) { submit.textContent = 'Sign & Accept'; submit.disabled = false; }
  }

  function openModal(esign) {
    esign = esign || _current;
    if (!esign) return;
    _current = esign;
    var m = _modalEl();
    var body = m.querySelector('[data-esign-body]');
    var foot = m.querySelector('[data-esign-foot]');
    var hosted = m.querySelector('[data-esign-hosted]');
    if (hosted) { hosted.hidden = true; if (esign.signingUrl) hosted.href = esign.signingUrl; }
    if (foot) foot.hidden = true;
    if (body) body.innerHTML = '<p class="cif-esign-loading" data-esign-loading>Loading your documents…</p>';
    m.hidden = false;
    requestAnimationFrame(function () { m.classList.add('is-open'); });
    document.body.classList.add('cif-modal-open');

    var url = '/api/my-esign/document' + (esign.id ? ('?esignId=' + encodeURIComponent(esign.id))
      : (esign.loanId ? ('?loanId=' + encodeURIComponent(esign.loanId)) : ''));
    fetch(url, { headers: { 'Authorization': 'Bearer ' + token(), 'Accept': 'application/json' }, credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        _renderDocs(body, data && data.document);
        if (foot) foot.hidden = false;
        _wireSubmit(esign);
      })
      .catch(function () {
        if (body) body.innerHTML = '<p class="cif-esign-error" style="display:block">We couldn’t load your documents. Please use the secure signing page below, or call (888) 999-9859.</p>';
        if (foot) foot.hidden = false;
        if (hosted && esign.signingUrl) hosted.hidden = false;
        _wireSubmit(esign);
      });
  }

  function hideModal() {
    if (_modal) { _modal.classList.remove('is-open'); _modal.hidden = true; }
    document.body.classList.remove('cif-modal-open');
  }

  // Payments page: replace the pay form with a "sign first" panel.
  function block(esign) {
    _current = esign || _current;
    var slot = document.querySelector('[data-esign-block-slot]');
    if (!slot) return false;
    slot.innerHTML =
      '<div class="pay-ach-blocked">' +
        '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/></svg>' +
        '<h3>Sign your agreement first</h3>' +
        '<p>Your loan isn’t active yet — there’s nothing to pay until you sign your loan agreement. It only takes a minute.</p>' +
        '<button type="button" class="app-cta-primary" data-esign-open style="margin-top:4px">Review &amp; sign</button>' +
      '</div>';
    slot.hidden = false;
    _hadPending = true;
    return true;
  }

  // Open-button delegation (strip CTA, block CTA, anything [data-esign-open]).
  document.addEventListener('click', function (e) {
    var t = e.target;
    while (t && t !== document) {
      if (t.getAttribute && t.getAttribute('data-esign-open') !== null) { e.preventDefault(); openModal(_current); return; }
      t = t.parentNode;
    }
  });

  // Auto-flip: when the customer comes back (e.g. from the hosted signing
  // page) and the loan has left the e-sign queue, reload so the portal shows
  // the now-active loan card. Only fires if we were showing a "sign" state.
  var _lastCheck = 0;
  function _onFocus() {
    if (document.visibilityState && document.visibilityState !== 'visible') return;
    if (!_hadPending) return;
    var now = Date.now();
    if (now - _lastCheck < 2500) return;
    _lastCheck = now;
    fetchPending(true).then(function (list) {
      if (!list || !list.length) { try { window.location.reload(); } catch (e) { /* ignore */ } }
    });
  }
  document.addEventListener('visibilitychange', _onFocus);
  window.addEventListener('focus', _onFocus);

  // Auto-surface the prompt on pages that opt in via a [data-esign-auto] slot
  // (e.g. profile) — pages that render a loan card drive the strip themselves.
  function _autoSurface() {
    if (!document.querySelector('[data-esign-auto]')) return;
    fetchPending().then(function (list) {
      if (list && list.length) {
        var p = list[0];
        renderStrip({ id: p.id, signingUrl: p.signingUrl, documentName: p.documentName, loanId: p.loanId });
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _autoSurface);
  else _autoSurface();

  function _money(n) { return (window.CifAch && CifAch.money) ? (CifAch.money(n) || '$0.00') : ('$' + Number(n || 0).toFixed(2)); }
  function _date(iso) { var d = (window.CifAch && CifAch.fmtDate) ? CifAch.fmtDate(iso) : iso; return d || '—'; }
  function _fig(label, value, cls) {
    return '<div class="loan-card-fig"><p class="loan-card-flabel">' + label + '</p>' +
      '<p class="loan-card-figval' + (cls ? (' ' + cls) : '') + '">' + value + '</p></div>';
  }

  // Make the active-loan card read correctly for an unsigned loan — IDENTICALLY
  // on every page. It's a "Pending Loan" (orange), the top pill moves into a
  // Status field, the balance shows as "Repay amount" (nothing owed until it
  // funds), loan amount + due date stay, repayment method is dropped, and the
  // "pay on time" note is hidden. The figure grid is rebuilt so the home, loans
  // and payments cards match exactly.
  function gateCard(card, loan) {
    if (!card) return;
    card.classList.add('is-pending-sign', 'loans-active');
    card.classList.remove('is-pastdue', 'is-pastdue-soft');
    var eb = card.querySelector('.loan-card-eyebrow');
    if (eb) eb.textContent = 'Pending Loan';
    var topPill = card.querySelector('[data-loan-status], [data-pay-loan-status]');
    if (topPill) topPill.style.display = 'none';
    var figs = card.querySelector('.loan-card-figures');
    if (figs && loan) {
      var amt = (loan.principal != null) ? loan.principal : loan.loanAmount;
      var repay = (loan.balance != null) ? loan.balance : loan.payoffAmount;
      figs.innerHTML =
        _fig('Loan Amount', _money(amt)) +
        _fig('Repay amount', _money(repay)) +
        _fig('Due Date', _date(loan.nextDueDate), 'loan-card-figval--date') +
        '<div class="loan-card-fig"><p class="loan-card-flabel">Status</p>' +
          '<p class="loan-card-method"><span class="cif-esign-statuschip">Awaiting signature</span></p></div>';
    }
    var hide = card.querySelectorAll('.loan-card-note, .loan-card-foot, .loan-card-rule');
    for (var i = 0; i < hide.length; i++) hide[i].style.display = 'none';
  }

  window.CifEsign = {
    fetchPending: fetchPending,
    gateCard: gateCard,
    infoForLoan: infoForLoan,
    isPending: isPending,
    applyPill: applyPill,
    renderStrip: renderStrip,
    openModal: openModal,
    hideModal: hideModal,
    block: block
  };
})();
