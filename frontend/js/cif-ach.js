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

  // Vergent puts an outstanding loan with a submitted ACH into "ACH Deposit
  // Hold". _shape_v1_loan forces status="Current" but passes the real text
  // through subStatus / rawStatus, so look there.
  function statusHold(loan) {
    if (!loan) return false;
    var s = ((loan.subStatus || '') + ' ' + (loan.rawStatus || '') + ' ' + (loan.status || '')).toLowerCase();
    if (s.indexOf('deposit hold') !== -1) return true;
    if (s.indexOf('ach') !== -1 && s.indexOf('hold') !== -1) return true;
    if (s.indexOf('pending deposit') !== -1) return true;
    return false;
  }
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
  // Returns {pending, amount, clearsBy, source} or null.
  function info(loan) {
    var sp = readSession(loan);
    var hold = statusHold(loan);
    if (!sp && !hold) return null;
    return {
      pending: true,
      amount: sp ? sp.amount : null,
      clearsBy: sp ? sp.clearsBy : null,
      source: sp ? 'session' : 'status'
    };
  }
  function setPending(obj) { try { sessionStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) { /* ignore */ } }

  // Consistent amber "Processing" pill on every active-loan card.
  function applyPill(pill) {
    if (!pill) return;
    pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due',
      'dash-pill--closed', 'pay-pill--pending');
    pill.classList.add('cif-pill-processing');
    pill.textContent = 'Processing';
  }

  function _stripHtml(inf) {
    var amt = (inf && inf.amount != null) ? (' of <strong>' + money(inf.amount) + '</strong>') : '';
    var by = (inf && inf.clearsBy)
      ? (' — estimated to clear by <strong>' + fmtDate(inf.clearsBy) + '</strong>')
      : ' (usually about 5 business days)';
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>' +
      '<span>Bank payment' + amt + ' is processing' + by +
      '. Your balance updates once it clears.</span>';
  }
  // Fill every [data-ach-strip-slot] anchor (or hide them when not pending).
  // Preserves each slot's existing classes (e.g. u-mobile / u-desktop) so
  // viewport visibility still works.
  function renderStrip(inf) {
    var slots = document.querySelectorAll('[data-ach-strip-slot]');
    for (var i = 0; i < slots.length; i++) {
      var slot = slots[i];
      if (!inf) { slot.hidden = true; slot.innerHTML = ''; continue; }
      if (!slot.classList.contains('cif-ach-strip')) slot.classList.add('cif-ach-strip');
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
        ' Bank (ACH) payments take about <strong>5 business days</strong> to clear. ' +
        'To avoid paying twice, you can make another payment once this one finishes.';
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
  function _anyModalOpen() {
    var ms = document.querySelectorAll('.profile-modal, .app-modal');
    for (var i = 0; i < ms.length; i++) { if (!ms[i].hidden) return true; }
    return false;
  }
  function _syncModalState() {
    document.body.classList.toggle('cif-modal-open', _anyModalOpen());
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
