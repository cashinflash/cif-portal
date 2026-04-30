/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller.
   - Fetches the customer's active loan summary and saved cards.
   - Lets them pick a card, set amount (defaults to amount due), pay.
   - On success, writes a sessionStorage flag so the dashboard can
     show a one-shot "payment posted" banner on next load.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/start.html';
  const SUCCESS_KEY = 'cif_payment_success';
  const REPAY_PORTAL_URL = 'https://cashinflash.repay.io/';

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
    window.location.replace(LOGIN_URL);
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
      // Parse body first so we can distinguish API-Gateway auth rejections
      // (no JSON body, or {message: "Unauthorized"}) from Lambda-returned
      // errors with a specific code. Only the former should log the user
      // out; the latter should surface as a normal error to the caller.
      return res.text().then(function (txt) {
        let body = {};
        try { body = txt ? JSON.parse(txt) : {}; } catch (e) { body = { raw: txt }; }

        if (res.status === 401 || res.status === 403) {
          const isLambdaErr = body && typeof body === 'object' && ('error' in body);
          if (!isLambdaErr) {
            sessionStorage.removeItem(TOKEN_KEY);
            window.location.replace(LOGIN_URL);
            throw new Error('unauthorized');
          }
          // Lambda-returned auth error — throw with the body attached.
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
    cards: [],
    banks: [],
    selectedCardId: null,
    selectedBankId: null,
    paymentMethod: 'card', // 'card' | 'bank'
    submitting: false,
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

  // ---------- Cards ----------
  function loadCards() {
    return api('/api/my-cards').then(function (data) {
      state.cards = (data && data.cards) || [];
      renderCards();
      return state.cards;
    });
  }

  // ---------- Banks (ACH) ----------
  function loadBanks() {
    return api('/api/my-banks').then(function (data) {
      state.banks = (data && data.banks) || [];
      renderBanks();
      return state.banks;
    }).catch(function () {
      state.banks = [];
      renderBanks();
    });
  }

  function renderBanks() {
    const root = qs('#payBankList');
    if (!root) return;
    root.innerHTML = '';
    if (!state.banks.length) {
      const wrap = document.createElement('div');
      wrap.className = 'pay-empty-card';
      wrap.innerHTML =
        '<div class="pay-empty-icon" aria-hidden="true">' +
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<rect x="3" y="10" width="18" height="11" rx="1"/><path d="M12 3l9 6H3l9-6z"/>' +
        '</svg></div>' +
        '<h3>Add a bank account to get started</h3>' +
        '<p>For your security, bank accounts can only be added in person. Visit any Cash in Flash location and we’ll set it up in minutes.</p>' +
        '<div class="pay-empty-actions">' +
        '<a href="tel:+17472707121" class="btn-apply">Call (747) 270-7121</a>' +
        '</div>' +
        '<small class="pay-empty-hint">New bank accounts appear here automatically as soon as we save them.</small>';
      root.appendChild(wrap);
      return;
    }
    state.banks.forEach(function (bank, idx) {
      const opt = document.createElement('label');
      opt.className = 'pay-card-option';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'bank';
      input.value = String(bank.id);
      if (idx === 0) {
        input.checked = true;
        state.selectedBankId = bank.id;
      }
      input.addEventListener('change', function () {
        state.selectedBankId = bank.id;
      });
      const body = document.createElement('span');
      body.className = 'pay-card-body';
      const strong = document.createElement('strong');
      strong.textContent = (bank.name || 'Bank') +
        ' · ' + (bank.last4 ? '••••' + bank.last4 : '••••');
      const small = document.createElement('small');
      small.textContent = (bank.accountType || 'Checking') +
        (bank.last4 ? ' · ends in ' + bank.last4 : '');
      body.appendChild(strong);
      body.appendChild(small);
      opt.appendChild(input);
      opt.appendChild(body);
      root.appendChild(opt);
    });
  }

  function renderCards() {
    const root = qs('#payCardList');
    if (!root) return;
    root.innerHTML = '';
    // Toggle the permanent "Adding a new debit card" secure-panel:
    // hide it when we're showing the rich empty-state below, since
    // the empty-state's CTA already covers "call us to add one".
    const securePanel = root.parentElement
      ? root.parentElement.querySelector('.pay-secure-panel')
      : null;
    if (!state.cards.length) {
      if (securePanel) securePanel.hidden = true;
      const wrap = document.createElement('div');
      wrap.className = 'pay-empty-card';
      wrap.innerHTML =
        '<div class="pay-empty-icon" aria-hidden="true">' +
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>' +
        '</svg></div>' +
        '<h3>Add a card to get started</h3>' +
        '<p>For your security, cards can only be added by a Cash in Flash agent. Call us and we’ll have one on your account in minutes.</p>' +
        '<div class="pay-empty-actions">' +
        '<a href="tel:+17472707121" class="btn-apply">Call (747) 270-7121</a>' +
        '</div>' +
        '<small class="pay-empty-hint">New cards appear here automatically as soon as your agent saves them.</small>';
      root.appendChild(wrap);
      return;
    }
    if (securePanel) securePanel.hidden = false;
    state.cards.forEach(function (card, idx) {
      const opt = document.createElement('label');
      opt.className = 'pay-card-option';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'card';
      input.value = String(card.id);
      if (idx === 0) {
        input.checked = true;
        state.selectedCardId = card.id;
      }
      input.addEventListener('change', function () {
        state.selectedCardId = card.id;
      });
      const body = document.createElement('span');
      body.className = 'pay-card-body';
      const strong = document.createElement('strong');
      strong.textContent = (card.brand || 'Card') + ' · ' + (card.last4 ? '•••• ' + card.last4 : '••••');
      const small = document.createElement('small');
      const mm = card.expMonth ? String(card.expMonth).padStart(2, '0') : '--';
      const yy = card.expYear ? String(card.expYear).slice(-2) : '--';
      small.textContent = 'exp ' + mm + '/' + yy;
      body.appendChild(strong);
      body.appendChild(small);
      opt.appendChild(input);
      opt.appendChild(body);
      root.appendChild(opt);
    });
  }

  // ---------- Form wiring ----------
  function initForm() {
    const formCard = qs('#payFormCard');
    if (!state.loan) {
      if (formCard) formCard.hidden = true;
      return;
    }
    if (formCard) formCard.hidden = false;

    const amountEl = qs('#payAmount');
    const hint = qs('#payAmountHint');
    const btn = qs('#payBtn');
    const defaultAmount = state.loan.nextDueAmount || state.loan.payoffAmount || state.loan.balance || 0;
    amountEl.value = Number(defaultAmount).toFixed(2);
    const payoff = Number(state.loan.payoffAmount || state.loan.balance || 0);
    hint.textContent = 'Maximum: ' + money(payoff);

    function updateBtn() {
      const amt = Number(amountEl.value);
      const haveMethod =
        (state.paymentMethod === 'card' && state.cards.length > 0 && state.selectedCardId) ||
        (state.paymentMethod === 'bank' && state.banks.length > 0 && state.selectedBankId);
      const ok = haveMethod && amt > 0 && amt <= payoff + 0.01 && !state.submitting;
      btn.disabled = !ok;
      btn.textContent = state.submitting ? 'Processing…' : ('Pay ' + money(amt));
    }
    amountEl.addEventListener('input', updateBtn);
    // Re-evaluate on tab / selection changes by polling via a MutationObserver
    // on the radio inputs — simpler: listen on the container.
    ['payCardList', 'payBankList'].forEach(function (id) {
      const root = qs('#' + id);
      if (root) root.addEventListener('change', updateBtn);
    });
    updateBtn();

    btn.addEventListener('click', function () {
      pay();
    });
  }

  // ---------- Tabs ----------
  function wireTabs() {
    const tabs = qsa('.pay-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        const which = tab.getAttribute('data-tab') || 'card';
        state.paymentMethod = which;
        tabs.forEach(function (t) {
          const isActive = t === tab;
          t.classList.toggle('is-active', isActive);
          t.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        qsa('.pay-panel').forEach(function (p) {
          p.hidden = p.getAttribute('data-panel') !== which;
        });
        initForm();
      });
    });
  }

  // ---------- Submit payment ----------
  function pay() {
    const errEl = qs('#payError');
    errEl.hidden = true;
    errEl.textContent = '';

    if (state.submitting || !state.loan) return;
    const amountEl = qs('#payAmount');
    const amount = Number(amountEl.value);
    if (!(amount > 0)) return;

    let body;
    if (state.paymentMethod === 'card') {
      if (!state.selectedCardId) return;
      body = {
        method: 'card',
        loanId: state.loan.id,
        cardId: state.selectedCardId,
        amount: Number(amount.toFixed(2)),
      };
    } else {
      if (!state.selectedBankId) return;
      body = {
        method: 'bank',
        loanId: state.loan.id,
        bankId: state.selectedBankId,
        amount: Number(amount.toFixed(2)),
      };
    }

    state.submitting = true;
    const btn = qs('#payBtn');
    btn.disabled = true;
    btn.textContent = 'Processing…';

    body.idempotencyKey = Date.now() + '-' + Math.random().toString(16).slice(2, 10);
    api('/api/my-payment', {
      method: 'POST',
      body: body,
    }).then(function (res) {
      if (res && res.success) {
        showReceipt(res, amount);
        sessionStorage.setItem(SUCCESS_KEY, JSON.stringify({
          amount: Number(amount.toFixed(2)),
          confirmationId: res.confirmationId || '',
          when: Date.now(),
        }));
        return;
      }
      const code = (res && res.error) || 'payment_failed';
      showError(code);
    }).catch(function (err) {
      const code = (err && err.body && err.body.error) || 'network_error';
      showError(code);
    }).finally(function () {
      state.submitting = false;
      const btn = qs('#payBtn');
      btn.disabled = false;
      btn.textContent = 'Pay ' + money(Number(qs('#payAmount').value));
    });
  }

  function showError(code) {
    const msg = {
      card_declined: 'Card was declined. Try a different card or call (747) 270-7121.',
      card_expired: 'That card has expired. Add a new one at a store.',
      card_not_yours: "We couldn't find that card on your account.",
      amount_invalid: 'Amount must be greater than $0 and no more than your balance.',
      loan_not_yours: "We couldn't post this payment to your loan. Call (747) 270-7121.",
      upstream_unavailable: "Our payment system is temporarily unavailable. Please try again in a minute.",
      network_error: 'Network error. Please check your connection and try again.',
      payment_failed: 'Payment failed. Please try again.',
    }[code] || 'Payment failed. Please try again.';
    const el = qs('#payError');
    el.textContent = msg;
    el.hidden = false;
  }

  function showReceipt(res, amount) {
    qs('#payFormCard').hidden = true;
    qs('#paySummary').hidden = true;
    const card = state.cards.find(function (c) { return String(c.id) === String(state.selectedCardId); });
    setText(qs('[data-receipt-amount]'), money(amount));
    setText(qs('[data-receipt-card]'),
      card ? ((card.brand || 'Card') + ' •••• ' + (card.last4 || '••••')) : 'card'
    );
    setText(qs('[data-receipt-confirmation]'), res.confirmationId || '—');
    setText(qs('[data-receipt-balance]'),
      res.newBalance !== null && res.newBalance !== undefined ? money(res.newBalance) : '—'
    );
    qs('#payReceipt').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function wireButtons() {
    wireTabs();
  }

  // ---------- Auto-refresh of payment methods ----------
  // No "click to refresh" button — that's bad UX for a customer
  // who just got off the phone with us. Instead, silently refetch
  // /api/my-cards + /api/my-banks at moments where a new payment
  // method is most likely to have just been added by an agent:
  //
  //   1. The browser tab regains focus (visibility change). The
  //      customer was probably on the phone or in a tab with
  //      Vergent's admin UI; coming back here means they expect
  //      to see the new card.
  //   2. A short delay (~3s) after initial page load — catches
  //      the case where the agent saved the card seconds before
  //      the customer hit the page.
  //   3. While the empty-state is showing AND the tab is
  //      foreground, gentle polling every 12s. We stop polling
  //      as soon as a card appears (or the customer leaves the
  //      tab). 12s is slow enough to be invisible, fast enough
  //      to feel "instant" while a customer waits on the phone.
  //
  // All refreshes are silent — no spinner, no flash, no UI churn
  // unless the underlying state actually changes.

  let pollTimer = null;

  function refreshMethods() {
    return Promise.all([
      loadCards().catch(function () {}),
      loadBanks().catch(function () {}),
    ]).then(function () {
      // updateBtn() is wired inside initForm via a listener on
      // the lists. Re-running initForm is unnecessary; the
      // re-rendered radios will fire change events when selected
      // and the existing payBtn watcher will react.
    });
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(function () {
      // Only poll while still empty AND tab is visible. Once a
      // card shows up (or the user leaves the tab), stop.
      const empty = state.cards.length === 0 && state.banks.length === 0;
      if (!empty || document.hidden) {
        stopPolling();
        return;
      }
      refreshMethods();
    }, 12000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      stopPolling();
      return;
    }
    // Tab just became visible — refetch immediately, then resume
    // gentle polling if still empty.
    refreshMethods().then(function () {
      const empty = state.cards.length === 0 && state.banks.length === 0;
      if (empty) startPolling();
    });
  });

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    wireButtons();
    Promise.all([loadLoan(), loadCards(), loadBanks()])
      .then(function () {
        initForm();
        // Fire one extra refetch a few seconds after first load —
        // catches the "agent saved card seconds before customer
        // hit refresh" case.
        setTimeout(function () { refreshMethods(); }, 3000);
        // If still empty, start gentle polling so newly-added
        // cards surface within ~12s while the customer waits.
        const empty = state.cards.length === 0 && state.banks.length === 0;
        if (empty && !document.hidden) startPolling();
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        const formCard = qs('#payFormCard');
        if (formCard) formCard.hidden = true;
        const errEl = qs('#payError');
        if (errEl) {
          errEl.textContent = 'Could not load your loan or card details. Please refresh.';
          errEl.hidden = false;
        }
      });
  });
})();
