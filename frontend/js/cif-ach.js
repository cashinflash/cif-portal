/* ═══════════════════════════════════════════════════════════════════
   CASH IN FLASH — shared pending-ACH helpers (window.CifAch)

   Loaded on dashboard, loans, and payments so the "bank payment is
   processing" treatment is IDENTICAL portal-wide: same detection, same
   amber "Processing" pill, same strip, same blocking modal, same dates.

   Pending is true when EITHER:
     • Vergent's loan shows an ACH hold (subStatus / rawStatus contains
       "ACH Deposit Hold") — robust across sessions and devices, OR
     • this browser just submitted one (sessionStorage cif_ach_pending) —
       covers the moment right after submit, before Vergent updates, and
       carries the exact estimated clear date.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var KEY = 'cif_ach_pending';

  // US Federal Reserve / bank holidays — ACH doesn't settle on these or
  // weekends. Keep in sync with _US_BANK_HOLIDAYS in handlers/payments.py.
  var HOLIDAYS = [
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-05-25', '2026-06-19',
    '2026-07-03', '2026-09-07', '2026-10-12', '2026-11-11', '2026-11-26',
    '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15', '2027-05-31',
    '2027-06-18', '2027-07-05', '2027-09-06', '2027-10-11', '2027-11-11',
    '2027-11-25', '2027-12-24'
  ];
  function pad(n) { return String(n).padStart(2, '0'); }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  // The date `n` banking days from today (skips weekends + Fed holidays).
  function addBusinessDays(n) {
    var d = new Date();
    var a = 0;
    while (a < n) {
      d.setDate(d.getDate() + 1);
      var dow = d.getDay();
      if (dow === 0 || dow === 6) continue;
      if (HOLIDAYS.indexOf(ymd(d)) !== -1) continue;
      a++;
    }
    return ymd(d);
  }
  function money(n) {
    var v = Number(n);
    if (n === null || n === undefined || isNaN(v)) return '';
    return v.toLocaleString('en-US', {
      style: 'currency', currency: 'USD',
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }
  function fmtDate(iso) {
    if (!iso) return '';
    var s = String(iso);
    if (s.length === 10) s += 'T00:00:00';  // local midnight (no UTC off-by-one)
    var d = new Date(s);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // Vergent is the source of truth. _shape_v1_loan forces status="Current"
  // for any outstanding loan but passes the REAL text through subStatus /
  // rawStatus, so the ACH lifecycle is read from there:
  //   • held/processing  → "ACH Deposit Hold"  → pending
  //   • returned (NSF…)  → "Returned …"        → returned
  //   • cleared          → "Deposited"/current, balance dropped → none
  // This is what makes the portal auto-update on clear/return/cancel.
  function _statusText(loan) {
    return loan ? ((loan.subStatus || '') + ' ' + (loan.rawStatus || '') + ' ' + (loan.status || '')).toLowerCase() : '';
  }
  function statusHold(loan) {
    var s = _statusText(loan);
    return s.indexOf('deposit hold') !== -1 ||
      (s.indexOf('ach') !== -1 && s.indexOf('hold') !== -1) ||
      s.indexOf('pending deposit') !== -1;
  }
  function statusReturned(loan) {
    var s = _statusText(loan);
    if (s.indexOf('nsf') !== -1) return true;
    if (s.indexOf('returned') !== -1) return true;
    if (s.indexOf('return') !== -1 && (s.indexOf('ach') !== -1 || s.indexOf('deposit') !== -1 ||
      s.indexOf('insufficient') !== -1 || s.indexOf('fund') !== -1)) return true;
    return false;
  }
  // Per-session "I just submitted" marker — bridges the gap between submit and
  // Vergent reflecting the hold. Per-SESSION (sessionStorage) on purpose: it
  // self-clears in a fresh session, so a manually-cancelled (unapproved) ACH
  // stops showing pending as soon as the customer reopens the app.
  function readSession(loan) {
    var p = null;
    try { p = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { p = null; }
    if (!p) return null;
    if (loan && p.loanId != null && String(p.loanId) !== String(loan.id)) return null;
    if (p.clearsBy) {
      var exp = new Date(p.clearsBy + 'T23:59:59').getTime() + 86400000;
      if (Date.now() > exp) { try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ } return null; }
    }
    return p;
  }
  // Cleared: Vergent posts the ACH ("Deposited") and the loan balance drops.
  // Distinct from "ACH Deposit Hold" (which contains "hold", caught above).
  function statusDeposited(loan) {
    var s = _statusText(loan);
    return s.indexOf('deposited') !== -1 && s.indexOf('hold') === -1;
  }
  // Returns { state: 'pending' | 'returned', amount, clearsBy } or null.
  // Vergent's status is AUTHORITATIVE: once it says Deposited (cleared) or
  // Returned, that overrides our per-session "just submitted" marker so the
  // portal never shows a stale "processing" after the payment resolves.
  function info(loan) {
    if (statusReturned(loan)) {
      try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
      return { state: 'returned', amount: null, clearsBy: null };
    }
    if (statusHold(loan)) {
      var sp1 = readSession(loan);
      return { state: 'pending', amount: sp1 ? sp1.amount : null, clearsBy: sp1 ? sp1.clearsBy : null };
    }
    if (statusDeposited(loan)) {
      try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }  // cleared → done
      return null;
    }
    var sp = readSession(loan);
    if (sp) return { state: 'pending', amount: sp.amount, clearsBy: sp.clearsBy };
    return null;
  }
  function setPending(obj) { try { sessionStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) { /* ignore */ } }

  // Consistent status pill on every active-loan card: amber "Processing"
  // while pending, red "Payment returned" if it bounced.
  function applyPill(pill, inf) {
    if (!pill) return;
    pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due',
      'dash-pill--closed', 'pay-pill--pending', 'cif-pill-processing', 'cif-pill-returned');
    if (inf && inf.state === 'returned') {
      pill.classList.add('cif-pill-returned');
      pill.textContent = 'Payment returned';
    } else {
      pill.classList.add('cif-pill-processing');
      pill.textContent = 'Processing';
    }
  }

  function _stripHtml(inf) {
    if (inf && inf.state === 'returned') {
      var ra = (inf.amount != null) ? (' of <strong>' + money(inf.amount) + '</strong>') : '';
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>' +
        '<span>Your recent bank payment' + ra + ' was <strong>returned</strong> (often for insufficient funds), so your balance wasn’t reduced. Please make a payment to keep your loan current.</span>';
    }
    var amt = (inf && inf.amount != null) ? (' of <strong>' + money(inf.amount) + '</strong>') : '';
    var by = (inf && inf.clearsBy)
      ? (' — estimated to clear by <strong>' + fmtDate(inf.clearsBy) + '</strong>')
      : ' (usually about 5 business days)';
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>' +
      '<span>Bank payment' + amt + ' is processing' + by +
      '. Your balance updates once it clears.</span>';
  }
  // Fill every [data-ach-strip-slot] anchor (or hide them when not pending).
  // Preserves each slot's existing classes (u-mobile / u-desktop).
  function renderStrip(inf) {
    var slots = document.querySelectorAll('[data-ach-strip-slot]');
    for (var i = 0; i < slots.length; i++) {
      var slot = slots[i];
      if (!inf) { slot.hidden = true; slot.innerHTML = ''; slot.classList.remove('is-returned'); continue; }
      if (!slot.classList.contains('cif-ach-strip')) slot.classList.add('cif-ach-strip');
      slot.classList.toggle('is-returned', inf.state === 'returned');
      slot.innerHTML = _stripHtml(inf);
      slot.hidden = false;
    }
  }

  var _modal = null;
  function _modalEl() {
    if (_modal) return _modal;
    var wrap = document.createElement('div');
    wrap.className = 'profile-modal cif-ach-modal';
    wrap.hidden = true;
    wrap.innerHTML =
      '<button type="button" class="profile-modal-backdrop" data-ach-close aria-label="Close"></button>' +
      '<div class="profile-modal-card" role="dialog" aria-modal="true" aria-labelledby="cifAchModalTitle">' +
        '<div class="profile-modal-head"><h3 class="profile-modal-title" id="cifAchModalTitle">Payment in progress</h3></div>' +
        '<div class="profile-modal-body">' +
          '<div class="pay-ach-note"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>' +
            '<div data-ach-modal-text></div></div>' +
          '<div class="profile-modal-actions" style="display:flex;justify-content:flex-end;margin-top:12px">' +
            '<button type="button" class="btn-apply" data-ach-close>Got it</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      if (e.target && e.target.hasAttribute && e.target.hasAttribute('data-ach-close')) hideModal();
    });
    _modal = wrap;
    return wrap;
  }
  function showBlockedModal(inf) {
    inf = inf || {};
    var m = _modalEl();
    var txt = m.querySelector('[data-ach-modal-text]');
    var amt = (inf.amount != null) ? (money(inf.amount) + ' ') : '';
    var by = inf.clearsBy ? (' It’s estimated to clear by <strong>' + fmtDate(inf.clearsBy) + '</strong>.') : '';
    if (txt) {
      txt.innerHTML = 'Your bank payment ' + amt + 'is still processing.' + by +
        ' Bank (ACH) payments take about <strong>5 business days</strong> to clear, ' +
        'and your balance updates once it does.';
    }
    m.hidden = false;
    requestAnimationFrame(function () { m.classList.add('is-open'); });
    _syncModalState();
  }
  function hideModal() {
    if (_modal) { _modal.classList.remove('is-open'); _modal.hidden = true; }
    _syncModalState();
  }

  // ── Mobile modal helper ──────────────────────────────────────────────
  // Every modal in the portal (.profile-modal / .app-modal, incl. the one
  // above) lives inside a page stacking context that sits BELOW the fixed
  // bottom tab bar, so on mobile the tab bar paints over the sheet and cuts
  // off its buttons. Fix it once, portal-wide: whenever any modal is open,
  // add body.cif-modal-open (CSS hides the tab bar + locks scroll).
  function _syncModalState() {
    var ms = document.querySelectorAll('.profile-modal, .app-modal');
    var anyOpen = false;
    for (var i = 0; i < ms.length; i++) {
      var m = ms[i];
      if (!m.hidden) {
        anyOpen = true;
        // Hoist the open modal to <body> so it escapes any page stacking
        // context that sits below the fixed footer/tab bar — that's what made
        // the footer text bleed through the sheet. At <body> its z-index wins.
        if (m.parentNode !== document.body) document.body.appendChild(m);
      }
    }
    document.body.classList.toggle('cif-modal-open', anyOpen);
  }
  var _modalObserver = null;
  function _watchModals() {
    if (typeof MutationObserver === 'undefined') return;
    if (_modalObserver) _modalObserver.disconnect();
    _modalObserver = new MutationObserver(_syncModalState);
    var ms = document.querySelectorAll('.profile-modal, .app-modal');
    for (var i = 0; i < ms.length; i++) {
      _modalObserver.observe(ms[i], { attributes: true, attributeFilter: ['hidden', 'class'] });
    }
    _syncModalState();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _watchModals);
  } else {
    _watchModals();
  }

  window.CifAch = {
    KEY: KEY,
    info: info,
    setPending: setPending,
    addBusinessDays: addBusinessDays,
    fmtDate: fmtDate,
    money: money,
    applyPill: applyPill,
    renderStrip: renderStrip,
    showBlockedModal: showBlockedModal,
    hideModal: hideModal
  };
})();
