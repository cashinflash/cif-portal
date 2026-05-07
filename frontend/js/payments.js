/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller (handoff via new tab).

   Vergent's customer portal is the actual payment surface. We mint
   a single-use handoff URL (so the customer is auto-signed-in there)
   and open it in a new tab. Our page transitions to a "waiting"
   state with an "I'm done — refresh balance" button.

   Why not iframe: Vergent serves X-Frame-Options: DENY (or CSP
   frame-ancestors) so the page can never load inside our site. The
   new-tab approach is the only path that works.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/start.html';
  const SUCCESS_KEY = 'cif_payment_success';

  function qs(sel, root) { return (root || document).querySelector(sel); }

  function money(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
      style: 'currency', currency: 'USD',
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
  }
  function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  function setText(el, v) { if (el) el.textContent = v; }

  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) {
    window.location.replace(LOGIN_URL + '?reason=session_expired');
    return;
  }

  function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({
      Authorization: 'Bearer ' + token,
      Accept: 'application/json',
    }, opts.headers || {});
    if (opts.body) headers['Content-Type'] = 'application/json';
    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: 'omit',
    }).then(function (res) {
      return res.text().then(function (txt) {
        let body = {};
        try { body = txt ? JSON.parse(txt) : {}; } catch (e) { body = { raw: txt }; }
        if (res.status === 401 || res.status === 403) {
          const isLambdaErr = body && typeof body === 'object' && ('error' in body);
          if (!isLambdaErr) {
            sessionStorage.removeItem(TOKEN_KEY);
            window.location.replace(LOGIN_URL + '?reason=session_expired');
            throw new Error('unauthorized');
          }
          const err = new Error('http ' + res.status);
          err.body = body;
          throw err;
        }
        if (!res.ok) {
          const err = new Error('http ' + res.status);
          err.body = body;
          throw err;
        }
        return body;
      });
    });
  }

  const state = {
    loan: null,
    submitting: false,
    refreshing: false,
    initialBalance: null,    // captured before opening the new tab
    lastHandoffUrl: null,
  };

  // ---------- Loan summary ----------
  function loadLoan() {
    return api('/api/my-payment/loan-summary').then(function (data) {
      const card = qs('#paySummary');
      const body = qs('.pay-summary-body', card);
      const empty = qs('.pay-summary-empty', card);
      const skel = qs('.dash-card-skeleton', card);
      if (skel) skel.style.display = 'none';
      card.setAttribute('aria-busy', 'false');

      if (!data || !data.loan) {
        if (body) body.hidden = true;
        if (empty) empty.hidden = false;
        return null;
      }
      const loan = data.loan;
      state.loan = loan;
      setText(qs('[data-pay-loan-id]', card), 'Loan #' + (loan.publicId || loan.id || '—'));
      setText(qs('[data-pay-balance]', card), money(loan.balance).replace(/^\$/, ''));
      const caption = qs('[data-pay-caption]', card);
      if (caption) {
        const parts = [];
        if (loan.nextDueDate) parts.push('Due ' + formatDate(loan.nextDueDate));
        if (loan.nextDueAmount) parts.push('Amount due ' + money(loan.nextDueAmount));
        caption.textContent = parts.join(' · ');
      }
      const pill = qs('[data-pay-loan-status]', card);
      if (pill) pill.textContent = loan.status || 'Current';
      if (body) body.hidden = false;
      return loan;
    });
  }

  // ---------- Open Vergent's secure payment page in a new tab ----------
  function startPayment() {
    if (state.submitting) return;
    const btn = qs('#payContinueBtn');
    const errEl = qs('#payError');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    state.submitting = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Opening secure page…';
    }

    state.initialBalance = state.loan ? Number(state.loan.balance) : null;

    api('/api/my-payment', {
      method: 'POST',
      body: { loanId: state.loan && state.loan.id },
    }).then(function (res) {
      const url = res && res.handoffUrl;
      if (!url) throw new Error('no_url');
      state.lastHandoffUrl = url;
      const w = window.open(url, '_blank', 'noopener,noreferrer');
      if (!w) {
        showError('popup_blocked');
        return;
      }
      transitionToWaiting();
    }).catch(function (err) {
      const code = (err && err.body && err.body.error) || 'handoff_failed';
      showError(code);
    }).finally(function () {
      state.submitting = false;
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Continue to secure payment';
      }
    });
  }

  function transitionToWaiting() {
    const formCard = qs('#payFormCard');
    const waitingCard = qs('#payWaitingCard');
    if (formCard) formCard.hidden = true;
    if (waitingCard) waitingCard.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function showError(code) {
    const msg = {
      handoff_failed:        "We couldn't open the secure payment page. Please try again, or call (747) 270-7121.",
      handoff_no_url:        "We couldn't open the secure payment page. Please try again in a minute.",
      popup_blocked:         "Your browser blocked the new tab. Please allow pop-ups for this site, then try again.",
      vergent_creds_missing: "Our payment system isn't configured. Please call (747) 270-7121.",
      no_loan:               "We couldn't find a loan to pay on. Try refreshing the page.",
      unauthorized:          'Your session expired. Please sign in again.',
    }[code] || "We couldn't open the secure payment page. Please try again.";
    const el = qs('#payError');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
  }

  // ---------- Refresh balance after the customer comes back ----------
  function refreshAfterPayment() {
    if (state.refreshing) return;
    state.refreshing = true;
    const btn = qs('#payDoneBtn');
    const note = qs('#payWaitingNote');
    if (note) { note.hidden = true; note.textContent = ''; }
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Refreshing…';
    }
    return loadLoan().then(function (loan) {
      const before = state.initialBalance;
      const after = loan ? Number(loan.balance) : null;
      const decreased = (before !== null && after !== null && after < before - 0.005);

      if (decreased) {
        const paid = before - after;
        showReceipt(paid, after);
        sessionStorage.setItem(SUCCESS_KEY, JSON.stringify({
          amount: Number(paid.toFixed(2)),
          when: Date.now(),
        }));
      } else if (note) {
        note.textContent = "We don't see a new payment yet. If you completed a payment, give it a minute and click again.";
        note.hidden = false;
      }
    }).finally(function () {
      state.refreshing = false;
      if (btn) {
        btn.disabled = false;
        btn.textContent = "I'm done — refresh my balance";
      }
    });
  }

  function reopenPaymentTab() {
    if (state.lastHandoffUrl) {
      window.open(state.lastHandoffUrl, '_blank', 'noopener,noreferrer');
    } else {
      // No prior URL — re-mint and open.
      startPayment();
    }
  }

  function showReceipt(amount, newBalance) {
    qs('#payFormCard').hidden = true;
    qs('#payWaitingCard').hidden = true;
    setText(qs('[data-receipt-amount]'), money(amount));
    setText(qs('[data-receipt-balance]'),
      newBalance !== null && newBalance !== undefined ? money(newBalance) : '—'
    );
    qs('#payReceipt').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    const continueBtn = qs('#payContinueBtn');
    if (continueBtn) continueBtn.addEventListener('click', startPayment);

    const doneBtn = qs('#payDoneBtn');
    if (doneBtn) doneBtn.addEventListener('click', refreshAfterPayment);

    const reopenBtn = qs('#payReopenBtn');
    if (reopenBtn) reopenBtn.addEventListener('click', reopenPaymentTab);

    loadLoan().then(function (loan) {
      const formCard = qs('#payFormCard');
      if (formCard) formCard.hidden = !loan;
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      const errEl = qs('#payError');
      if (errEl) {
        errEl.textContent = 'Could not load your loan details. Please refresh.';
        errEl.hidden = false;
      }
    });

    // When the customer returns to this tab from the Vergent payment
    // page, auto-refresh the loan summary in the background. If the
    // balance dropped, we surface it without making them click anything.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) return;
      const waitingCard = qs('#payWaitingCard');
      if (!waitingCard || waitingCard.hidden) return;
      // We're in the waiting state and the tab just regained focus —
      // soft-refresh balance to detect a payment.
      refreshAfterPayment();
    });
  });
})();
