/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller.

   The portal hands off to Vergent's hosted customer-portal page for
   the actual payment ceremony. We show the loan balance + a single
   "Continue to secure payment page" button. Clicking it asks the
   backend for a single-use handoff URL (Vergent's
   /api/authenticate/handoff/create), opens that URL in a new tab,
   and then shows a "When you're done, refresh this page" prompt.
   When the customer comes back, /api/my-payment/loan-summary
   reflects the updated balance.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/start.html';

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

  const state = { loan: null, submitting: false };

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

  // ---------- Handoff ----------
  function startHandoff() {
    if (state.submitting) return;
    const btn = qs('#payContinueBtn');
    const errEl = qs('#payError');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    state.submitting = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Opening secure page…';
    }

    api('/api/my-payment', { method: 'POST', body: {} })
      .then(function (res) {
        const url = res && res.handoffUrl;
        if (!url) throw new Error('no_url');
        // Open in a new tab. Some browsers block window.open if it's
        // not directly tied to a click — this handler runs synchronously
        // inside the click, so it should be fine.
        const w = window.open(url, '_blank', 'noopener,noreferrer');
        if (!w) {
          // Popup was blocked — show a fallback link the customer
          // can click to navigate themselves.
          showPopupBlocked(url);
          return;
        }
        showWaiting();
      })
      .catch(function (err) {
        const code = (err && err.body && err.body.error) || 'handoff_failed';
        showError(code);
      })
      .finally(function () {
        state.submitting = false;
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Continue to secure payment page';
        }
      });
  }

  function showError(code) {
    const msg = {
      handoff_failed:        "We couldn't open the secure payment page. Please try again, or call (747) 270-7121.",
      handoff_no_url:        "We couldn't open the secure payment page. Please try again in a minute.",
      apim_unavailable:      "Our payment system is temporarily unavailable. Please try again in a minute.",
      vergent_creds_missing: "Our payment system isn't configured. Please call (747) 270-7121.",
      unauthorized:          'Your session expired. Please sign in again.',
    }[code] || "We couldn't open the secure payment page. Please try again.";
    const el = qs('#payError');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
  }

  function showPopupBlocked(url) {
    const el = qs('#payPopupBlocked');
    if (!el) return;
    const link = qs('#payPopupBlockedLink', el);
    if (link) link.href = url;
    el.hidden = false;
  }

  function showWaiting() {
    const el = qs('#payWaiting');
    if (!el) return;
    el.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    const btn = qs('#payContinueBtn');
    if (btn) btn.addEventListener('click', startHandoff);
    const refreshBtn = qs('#payRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', function () {
      window.location.reload();
    });

    loadLoan().catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      const errEl = qs('#payError');
      if (errEl) {
        errEl.textContent = 'Could not load your loan details. Please refresh.';
        errEl.hidden = false;
      }
    });

    // When the tab regains focus (customer came back from Vergent's
    // payment page), refresh the summary so the new balance shows.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        loadLoan().catch(function () {});
      }
    });
  });
})();
