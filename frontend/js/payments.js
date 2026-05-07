/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller (iframe-modal flow).

   Why an iframe modal: Vergent's REST surface is locked down for
   server-to-server card charges (see backend/handlers/payments.py
   for the full list of broken endpoints). The handoff URL endpoint
   IS reachable and signs the customer into Vergent's hosted payment
   page. Embedding that page in an iframe modal makes the UX feel
   in-portal while letting Vergent handle the actual charge.

   If Vergent's X-Frame-Options blocks the iframe, we show a
   fallback "Open secure payment page" link that opens it in a new
   tab — same flow, just a click further.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/start.html';
  const SUCCESS_KEY = 'cif_payment_success';

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

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

  // ---------- State ----------
  const state = {
    loan: null,
    submitting: false,
    initialBalance: null,    // captured before opening the modal
    iframeBlockedTimer: null,
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

  // ---------- Iframe modal ----------
  function openIframeModal(handoffUrl) {
    const modal = qs('#payIframeModal');
    const iframe = qs('#payIframe');
    const blocked = qs('#payIframeBlocked');
    const blockedLink = qs('#payIframeBlockedLink');
    if (!modal || !iframe || !blocked || !blockedLink) return;

    blocked.hidden = true;
    blockedLink.href = handoffUrl;
    iframe.src = handoffUrl;
    document.body.style.overflow = 'hidden';
    modal.hidden = false;

    // Detection: if the iframe doesn't reach a same-or-cross-origin
    // load event within 5s, assume Vergent's X-Frame-Options blocked
    // it. Show the fallback "open in new tab" link.
    if (state.iframeBlockedTimer) clearTimeout(state.iframeBlockedTimer);
    let loaded = false;
    iframe.addEventListener('load', function () {
      loaded = true;
    }, { once: true });
    state.iframeBlockedTimer = setTimeout(function () {
      if (!loaded) blocked.hidden = false;
    }, 5000);
  }

  function closeIframeModal() {
    const modal = qs('#payIframeModal');
    const iframe = qs('#payIframe');
    if (modal) modal.hidden = true;
    if (iframe) iframe.src = 'about:blank';
    document.body.style.overflow = '';
    if (state.iframeBlockedTimer) {
      clearTimeout(state.iframeBlockedTimer);
      state.iframeBlockedTimer = null;
    }
  }

  // ---------- Continue button ----------
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

    // Capture balance before the modal opens so we can detect a
    // payment by looking for a balance decrease on refresh.
    state.initialBalance = state.loan ? Number(state.loan.balance) : null;

    api('/api/my-payment', {
      method: 'POST',
      body: { loanId: state.loan && state.loan.id },
    }).then(function (res) {
      const url = res && res.handoffUrl;
      if (!url) throw new Error('no_url');
      openIframeModal(url);
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

  function showError(code) {
    const msg = {
      handoff_failed:        "We couldn't open the secure payment page. Please try again, or call (747) 270-7121.",
      handoff_no_url:        "We couldn't open the secure payment page. Please try again in a minute.",
      vergent_creds_missing: "Our payment system isn't configured. Please call (747) 270-7121.",
      no_loan:               "We couldn't find a loan to pay on. Try refreshing the page.",
      unauthorized:          'Your session expired. Please sign in again.',
    }[code] || "We couldn't open the secure payment page. Please try again.";
    const el = qs('#payError');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
  }

  // ---------- "I'm done" — refresh balance, show receipt if changed ----------
  function refreshAfterPayment() {
    const btn = qs('#payIframeDoneBtn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Refreshing…';
    }
    return loadLoan().then(function (loan) {
      const before = state.initialBalance;
      const after = loan ? Number(loan.balance) : null;
      const decreased = (before !== null && after !== null && after < before - 0.005);

      closeIframeModal();
      if (decreased) {
        const paid = before - after;
        showReceipt(paid, after);
        sessionStorage.setItem(SUCCESS_KEY, JSON.stringify({
          amount: Number(paid.toFixed(2)),
          when: Date.now(),
        }));
      } else {
        // Balance didn't change — probably canceled or still processing.
        const errEl = qs('#payError');
        if (errEl) {
          errEl.textContent = "We don't see a new payment yet. If you completed a payment, give it a minute and refresh — or call us if it doesn't show up.";
          errEl.hidden = false;
        }
      }
    }).finally(function () {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "I'm done — refresh my balance";
      }
    });
  }

  function showReceipt(amount, newBalance) {
    qs('#payFormCard').hidden = true;
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

    const doneBtn = qs('#payIframeDoneBtn');
    if (doneBtn) doneBtn.addEventListener('click', refreshAfterPayment);

    qsa('[data-action="pay-modal-close"]').forEach(function (el) {
      el.addEventListener('click', function () { closeIframeModal(); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        const modal = qs('#payIframeModal');
        if (modal && !modal.hidden) closeIframeModal();
      }
    });

    loadLoan().then(function (loan) {
      // Reveal the Continue card once we have an active loan.
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
  });
})();
