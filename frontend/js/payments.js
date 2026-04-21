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
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL);
        throw new Error('unauthorized');
      }
      return res.json().then(function (body) {
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
    selectedCardId: null,
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

  function renderCards() {
    const root = qs('#payCardList');
    if (!root) return;
    root.innerHTML = '';
    if (!state.cards.length) {
      const p = document.createElement('p');
      p.className = 'pay-empty';
      p.textContent = 'No saved cards on your account. Call (747) 270-7121 or visit a store to add one.';
      root.appendChild(p);
      return;
    }
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
      const ok = state.cards.length > 0 && amt > 0 && amt <= payoff + 0.01 && !state.submitting;
      btn.disabled = !ok;
      btn.textContent = state.submitting ? 'Processing…' : ('Pay ' + money(amt));
    }
    amountEl.addEventListener('input', updateBtn);
    updateBtn();

    btn.addEventListener('click', function () {
      pay();
    });
  }

  // ---------- Submit payment ----------
  function pay() {
    const errEl = qs('#payError');
    errEl.hidden = true;
    errEl.textContent = '';

    if (state.submitting || !state.loan || !state.selectedCardId) return;
    const amountEl = qs('#payAmount');
    const amount = Number(amountEl.value);
    if (!(amount > 0)) return;

    state.submitting = true;
    const btn = qs('#payBtn');
    btn.disabled = true;
    btn.textContent = 'Processing…';

    const idempotencyKey = (Date.now() + '-' + Math.random().toString(16).slice(2, 10));
    api('/api/my-payment', {
      method: 'POST',
      body: {
        loanId: state.loan.id,
        cardId: state.selectedCardId,
        amount: Number(amount.toFixed(2)),
        idempotencyKey: idempotencyKey,
      },
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

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    Promise.all([loadLoan(), loadCards()])
      .then(function () { initForm(); })
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
