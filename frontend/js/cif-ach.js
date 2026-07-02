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
    // achStatusText is derived server-side from Vergent's StatusId (the loan-
    // list endpoint returns the text Status/SubStatus blank for outstanding
    // loans, so this is what actually carries "ACH Deposit Hold" / "Returned" /
    // "Deposited" through to the portal). subStatus/rawStatus kept for any
    // record that does surface the text directly.
    return loan ? ((loan.achStatusText || '') + ' ' + (loan.subStatus || '') + ' ' + (loan.rawStatus || '') + ' ' + (loan.status || '')).toLowerCase() : '';
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
  // Durable server record (loan.achPending) — persisted when the portal submits
  // an ACH, so the pending block + the REAL clear date + the bank last-4 survive
  // a different device or an operator "view as customer" (which have no
  // sessionStorage). Vergent status still overrides it on resolve (below).
  function serverRec(loan) {
    var r = loan && loan.achPending;
    if (!r) return null;
    return {
      amount: (r.amount != null ? Number(r.amount) : null),
      clearsBy: r.clearsBy || null,
      accountLast4: r.accountLast4 || null,
      accountType: r.accountType || null,
      returnReason: r.returnReason || null,
      submittedAtMs: (r.submittedAtMs != null ? Number(r.submittedAtMs) : null)
    };
  }
  // Turn Vergent's ACH-return SubStatus (a NACHA code or short text) into a
  // customer-friendly phrase. Unknown values pass through as-is.
  function _prettyReason(r) {
    var s = String(r || '').trim();
    if (!s) return '';
    var low = s.toLowerCase();
    if (low.indexOf('nsf') !== -1 || low === 'r01' || low === 'r09' || low.indexOf('insuffic') !== -1 || low.indexOf('fund') !== -1) return 'insufficient funds';
    if (low === 'r02' || low.indexOf('closed') !== -1) return 'the bank account was closed';
    if (low === 'r03' || low === 'r04' || low.indexOf('no account') !== -1 || low.indexOf('locate') !== -1 || low.indexOf('invalid account') !== -1) return 'the account could not be found';
    if (low === 'r08' || low.indexOf('stop') !== -1) return 'a stop payment';
    if (low === 'r10' || low === 'r29' || low.indexOf('unauthor') !== -1) return 'the payment was not authorized';
    if (low === 'r16' || low.indexOf('frozen') !== -1) return 'the account was frozen';
    return s;  // already human-readable
  }
  // A durable record is "fresh" enough to ASSERT pending during the pre-status
  // gap (before Vergent shows the hold). Vergent flips within ~8h; give a
  // generous 48h bridge, after which we defer to Vergent so a cancelled/settled
  // ACH never sticks as pending on an otherwise-normal loan. (No timestamp →
  // trust it.)
  function freshRec(rec) {
    if (!rec || rec.submittedAtMs == null) return true;
    return (Date.now() - rec.submittedAtMs) < 48 * 3600 * 1000;
  }
  // "Checking •• 6789" / "Savings •• 1234" / "Bank account" from a record.
  function acctLabel(det) {
    if (!det) return null;
    var t = String(det.accountType || '').toLowerCase();
    var kind = t.indexOf('sav') !== -1 ? 'Savings'
      : (t.indexOf('check') !== -1 ? 'Checking' : '');
    if (det.accountLast4) return (kind || 'Bank') + ' •• ' + det.accountLast4;
    return kind ? (kind + ' account') : 'Bank account';
  }
  // Returns { state:'pending'|'returned', amount, clearsBy, account } or null.
  // Vergent's status is AUTHORITATIVE: once it says Deposited (cleared) or
  // Returned, that overrides BOTH the durable record and the per-session marker
  // so the portal never shows a stale "processing" after the payment resolves.
  // Details (amount / clearsBy / account) prefer the durable server record so
  // they're identical on every device; they fall back to this session's marker.
  function info(loan) {
    var rec = serverRec(loan);
    var sp = readSession(loan);
    var det = rec || sp || null;
    if (statusReturned(loan)) {
      try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
      return { state: 'returned', amount: det ? det.amount : null, clearsBy: null, account: acctLabel(det), reason: det ? det.returnReason : null };
    }
    if (statusHold(loan)) {
      return { state: 'pending', amount: det ? det.amount : null, clearsBy: det ? det.clearsBy : null, account: acctLabel(det) };
    }
    if (statusDeposited(loan)) {
      try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }  // cleared → done
      return null;
    }
    // Pre-status gap (Vergent shows no ACH signal yet): a FRESH durable record
    // or this session's marker asserts pending.
    if (rec && freshRec(rec)) return { state: 'pending', amount: rec.amount, clearsBy: rec.clearsBy, account: acctLabel(rec) };
    if (sp) return { state: 'pending', amount: sp.amount, clearsBy: sp.clearsBy, account: acctLabel(sp) };
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

  // Repayment-method label on the active-loan card. When a bank (ACH) payment
  // is the active repayment, the loan's method IS the bank account — show that
  // (with a bank glyph), never whatever debit card happens to be saved on file.
  // Flips a flag so the async card loaders (loadCards / loadRepaymentMethod)
  // skip re-stamping the card label over this, whichever order they resolve in.
  var _BANK_ICO = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="21" x2="21" y2="21"/><line x1="3" y1="10" x2="21" y2="10"/><polyline points="5 6 12 3 19 6"/><line x1="4" y1="10" x2="4" y2="21"/><line x1="20" y1="10" x2="20" y2="21"/><line x1="8" y1="14" x2="8" y2="17"/><line x1="12" y1="14" x2="12" y2="17"/><line x1="16" y1="14" x2="16" y2="17"/></svg>';
  function setRepayMethodBank(label) {
    window.__cifAchMethodActive = true;
    var els = document.querySelectorAll('[data-loan-repay-method]');
    for (var i = 0; i < els.length; i++) {
      els[i].textContent = label || 'Bank account';
      var p = els[i].parentNode;
      var svg = p && p.querySelector('svg');
      if (svg) svg.outerHTML = _BANK_ICO;
    }
  }

  function _stripHtml(inf) {
    if (inf && inf.state === 'returned') {
      var ra = (inf.amount != null) ? (' of <strong>' + money(inf.amount) + '</strong>') : '';
      // Show Vergent's actual reason when we have it (e.g. "insufficient funds",
      // "the bank account was closed"); otherwise the neutral fallback.
      var pretty = inf.reason ? _prettyReason(inf.reason) : '';
      var rr = pretty ? (' (' + pretty + ')') : ' (often for insufficient funds)';
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>' +
        '<span>Your recent bank payment' + ra + ' was <strong>returned</strong>' + rr + ', so your balance wasn’t reduced. Please make a payment to keep your loan current.</span>';
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
    // Flag the page so CSS can reflow the desktop dashboard grid (drop the
    // strip into its own row under the loan card) and tuck the loans-page
    // strip up under the card — instead of letting the strip auto-place into
    // an empty grid cell at the very bottom.
    try { document.documentElement.classList.toggle('cif-ach-pending', !!inf); } catch (e) { /* ignore */ }
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
    // Centered hero card matching the pay-page confirm modal (.pay-cc-modal),
    // not a bottom-sheet — amber "in progress" theme with a clock. Styles live
    // in dashboard.css (.cif-ach-modal*), loaded portal-wide.
    wrap.innerHTML =
      '<button type="button" class="profile-modal-backdrop" data-ach-close aria-label="Close"></button>' +
      '<div class="profile-modal-card" role="dialog" aria-modal="true" aria-labelledby="cifAchModalTitle">' +
        '<div class="cif-ach-modal-hero">' +
          '<div class="cif-ach-modal-ico"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg></div>' +
          '<h3 class="cif-ach-modal-eyebrow" id="cifAchModalTitle">Payment in progress</h3>' +
          '<div class="cif-ach-modal-amount" data-ach-modal-amount>&nbsp;</div>' +
          '<div class="cif-ach-modal-sub" data-ach-modal-sub>from your bank account</div>' +
        '</div>' +
        '<div class="cif-ach-modal-body">' +
          '<p class="cif-ach-modal-note" data-ach-modal-text></p>' +
          '<div class="cif-ach-modal-actions">' +
            '<button type="button" class="cif-ach-modal-btn" data-ach-close>Got it</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('[data-ach-close]')) hideModal();
    });
    _modal = wrap;
    return wrap;
  }
  function showBlockedModal(inf) {
    inf = inf || {};
    var m = _modalEl();
    var amtEl = m.querySelector('[data-ach-modal-amount]');
    var subEl = m.querySelector('[data-ach-modal-sub]');
    var txt = m.querySelector('[data-ach-modal-text]');
    if (amtEl && subEl) {
      if (inf.amount != null) {
        amtEl.textContent = money(inf.amount);
        amtEl.style.display = '';
        subEl.textContent = 'from your bank account';
      } else {
        amtEl.style.display = 'none';
        subEl.textContent = 'Your bank payment is processing';
      }
    }
    var by = inf.clearsBy ? (' It’s estimated to clear by <strong>' + fmtDate(inf.clearsBy) + '</strong>.') : '';
    if (txt) {
      txt.innerHTML = 'Your bank payment is still processing, so you can’t start another payment just yet.' + by +
        ' Bank (ACH) payments take about <strong>5 business days</strong> to clear, and your balance updates automatically once it does.';
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
    setRepayMethodBank: setRepayMethodBank,
    showBlockedModal: showBlockedModal,
    hideModal: hideModal
  };
})();
