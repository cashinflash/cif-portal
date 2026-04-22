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

  function refreshCards() {
    // Called after a successful Add Card. Silently re-pulls cards + banks
    // and re-inits the form so the new card is selectable.
    return Promise.all([loadCards(), loadBanks()]).then(function () { initForm(); });
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
      const p = document.createElement('p');
      p.className = 'pay-empty';
      p.textContent = 'No bank account on file. Visit any Cash in Flash location to add one.';
      root.appendChild(p);
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
    const addBtn = qs('#payAddCardBtn');
    if (addBtn) addBtn.addEventListener('click', openAddCardModal);
    wireAddCardModal();
    wireTabs();
  }

  // ---------- Add Card modal ----------
  function openAddCardModal() {
    const modal = qs('#payAddCardModal');
    if (!modal) return;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    clearAddCardForm();
    setTimeout(function () {
      const first = qs('#cardName');
      if (first) first.focus();
    }, 10);
  }

  function closeAddCardModal() {
    const modal = qs('#payAddCardModal');
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function clearAddCardForm() {
    ['cardName', 'cardNumber', 'cardExp', 'cardCcv'].forEach(function (id) {
      const el = qs('#' + id);
      if (el) el.value = '';
    });
    const err = qs('#addCardError');
    if (err) { err.hidden = true; err.textContent = ''; }
    const brand = qs('#cardBrand');
    if (brand) brand.textContent = '';
    const sub = qs('#addCardSubmit');
    if (sub) { sub.disabled = false; sub.textContent = 'Save card'; }
  }

  function wireAddCardModal() {
    qsa('[data-close-modal]').forEach(function (el) {
      el.addEventListener('click', closeAddCardModal);
    });
    window.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        const modal = qs('#payAddCardModal');
        if (modal && !modal.hidden) closeAddCardModal();
      }
    });

    const num = qs('#cardNumber');
    if (num) num.addEventListener('input', onCardNumberInput);
    const exp = qs('#cardExp');
    if (exp) exp.addEventListener('input', onExpInput);
    const ccv = qs('#cardCcv');
    if (ccv) ccv.addEventListener('input', function () {
      ccv.value = ccv.value.replace(/\D/g, '').slice(0, 4);
    });

    const form = qs('#addCardForm');
    if (form) form.addEventListener('submit', onAddCardSubmit);
  }

  function onCardNumberInput() {
    const el = qs('#cardNumber');
    // Hard-cap at 16 for debit (Visa/MC/Discover). Amex debit is 15.
    // We don't accept 19-digit Visa credit-only variants for the
    // portal; all CIF card-on-file usage is a 16-digit debit.
    let rawDigits = el.value.replace(/\D/g, '');
    const brand = detectBrand(rawDigits);
    const cap = {
      Visa: 16, MasterCard: 16, Amex: 15, Discover: 16,
    }[brand] || 16;
    const digits = rawDigits.slice(0, cap);
    let grouped;
    if (brand === 'Amex') {
      // 4-6-5 groups
      grouped = (digits.slice(0, 4) +
        (digits.length > 4 ? ' ' + digits.slice(4, 10) : '') +
        (digits.length > 10 ? ' ' + digits.slice(10, 15) : '')).trim();
    } else {
      grouped = digits.replace(/(\d{4})(?=\d)/g, '$1 ');
    }
    el.value = grouped;
    setBrandTag(brand);
    // Set CCV length appropriately: Amex uses 4 digits, others use 3.
    const ccv = qs('#cardCcv');
    if (ccv) {
      ccv.setAttribute('maxlength', brand === 'Amex' ? '4' : '3');
      ccv.setAttribute('placeholder', brand === 'Amex' ? '4 digits' : '3 digits');
    }
  }

  function onExpInput() {
    const el = qs('#cardExp');
    const digits = el.value.replace(/\D/g, '').slice(0, 4);
    if (digits.length <= 2) el.value = digits;
    else el.value = digits.slice(0, 2) + '/' + digits.slice(2);
  }

  function detectBrand(digits) {
    if (!digits) return '';
    if (digits[0] === '4') return 'Visa';
    const two = digits.slice(0, 2);
    if (two === '34' || two === '37') return 'Amex';
    if (['51', '52', '53', '54', '55'].indexOf(two) >= 0) return 'MasterCard';
    const four = parseInt(digits.slice(0, 4) || '0', 10);
    if (four >= 2221 && four <= 2720) return 'MasterCard';
    if (digits.slice(0, 4) === '6011' || digits.slice(0, 2) === '65') return 'Discover';
    const six = parseInt(digits.slice(0, 6) || '0', 10);
    if (six >= 622126 && six <= 622925) return 'Discover';
    return '';
  }

  function setBrandTag(brand) {
    const el = qs('#cardBrand');
    if (el) el.textContent = brand || '';
  }

  function luhn(digits) {
    if (!digits) return false;
    let sum = 0;
    for (let i = digits.length - 1, flip = false; i >= 0; i--, flip = !flip) {
      let n = parseInt(digits[i], 10);
      if (flip) { n *= 2; if (n > 9) n -= 9; }
      sum += n;
    }
    return sum % 10 === 0;
  }

  function onAddCardSubmit(e) {
    e.preventDefault();
    const err = qs('#addCardError');
    err.hidden = true; err.textContent = '';

    const name = (qs('#cardName').value || '').trim();
    const pan = (qs('#cardNumber').value || '').replace(/\D/g, '');
    const expRaw = (qs('#cardExp').value || '').replace(/\D/g, '');
    const ccv = (qs('#cardCcv').value || '').replace(/\D/g, '');

    if (!name) return addCardFail('Please enter the cardholder name.');
    if (!(pan.length >= 13 && pan.length <= 19)) return addCardFail('Card number looks incomplete.');
    if (!luhn(pan)) return addCardFail('Card number looks invalid. Please check and try again.');
    if (expRaw.length < 4) return addCardFail('Enter expiration as MM/YY.');
    const mm = parseInt(expRaw.slice(0, 2), 10);
    const yy = parseInt(expRaw.slice(2, 4), 10);
    if (!(mm >= 1 && mm <= 12)) return addCardFail('That expiration month isn\'t valid.');
    const fullYear = 2000 + yy;
    const now = new Date();
    const endOfExpMonth = new Date(fullYear, mm, 0, 23, 59, 59);
    if (endOfExpMonth < now) return addCardFail('This card has already expired.');
    if (!(ccv.length >= 3 && ccv.length <= 4)) return addCardFail('CVV should be 3 or 4 digits.');

    const sub = qs('#addCardSubmit');
    sub.disabled = true;
    sub.textContent = 'Saving…';

    api('/api/my-cards', {
      method: 'POST',
      body: {
        cardHolderName: name,
        cardNumber: pan,
        expireMonth: mm,
        expireYear: fullYear,
        ccv: ccv,
        cardType: detectBrand(pan),
      },
    }).then(function (res) {
      if (res && res.success) {
        closeAddCardModal();
        showCardToast();
        refreshCards();
        return;
      }
      addCardFail(humanizeAddCardError((res && res.error) || 'card_declined'));
    }).catch(function (err) {
      const code = (err && err.body && err.body.error) || 'network_error';
      addCardFail(humanizeAddCardError(code));
    }).finally(function () {
      sub.disabled = false;
      sub.textContent = 'Save card';
    });
  }

  function humanizeAddCardError(code) {
    return ({
      card_invalid: 'Card number looks invalid. Please check and try again.',
      card_declined: 'We couldn\'t save that card. Please try a different one.',
      exp_invalid: 'That expiration date isn\'t valid.',
      ccv_invalid: 'CVV should be 3 or 4 digits.',
      name_invalid: 'Please check the cardholder name.',
      bad_body: 'Something about the card entry is off. Please try again.',
      upstream_unavailable: 'Our payment system is temporarily unavailable. Try again in a minute.',
      network_error: 'Network error. Please check your connection and try again.',
    })[code] || 'Could not save the card. Please try again.';
  }

  function addCardFail(msg) {
    const err = qs('#addCardError');
    err.textContent = msg;
    err.hidden = false;
    const sub = qs('#addCardSubmit');
    if (sub) { sub.disabled = false; sub.textContent = 'Save card'; }
  }

  function showCardToast() {
    const t = qs('#payCardToast');
    if (!t) return;
    t.hidden = false;
    t.classList.add('is-visible');
    setTimeout(function () {
      t.classList.remove('is-visible');
      setTimeout(function () { t.hidden = true; }, 300);
    }, 2800);
  }

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    wireButtons();
    Promise.all([loadLoan(), loadCards(), loadBanks()])
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
