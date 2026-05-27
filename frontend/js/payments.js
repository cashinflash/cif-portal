/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller (saved-card flow).

   Customer either:
     a) Picks a saved card from their list → enters CVV + amount →
        Pay now. We POST {paymentMethodId, cvv, amount} to
        /api/my-payment/charge.
     b) "Add a new card" → enters full PAN + exp + CVV + name +
        zip + amount → Pay now. We POST {cardNumber, expMonth,
        expYear, cvv, nameOnCard, zip, amount}. On success the
        backend auto-tokenizes via Repay CardSafe and stores in
        DDB so the card appears in the saved list next time.

   No Vergent handoff. PAN-on-PCI scope is SAQ A-EP for the new-card
   path; the saved-card path is strictly tighter (card_token only).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/start.html';
  const SUCCESS_KEY = 'cif_payment_success';
  const ADD_NEW_VALUE = '__add_new__';

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
  function escapeHtml(s) {
    return String(s || '').replace(/[<>&"]/g, function (c) {
      return ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'})[c];
    });
  }

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
    methods: [],
    selectedMethodId: ADD_NEW_VALUE,
    submitting: false,
    initialBalance: null,
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
      // Pre-fill amount with next-due or balance.
      const amountInput = qs('#payAmount');
      if (amountInput && !amountInput.value) {
        const preset = Number(loan.nextDueAmount || loan.balance || 0);
        if (preset > 0) amountInput.value = preset.toFixed(2);
      }
      return loan;
    });
  }

  // ---------- Saved methods ----------
  function loadMethods() {
    return api('/api/my-payment-methods').then(function (data) {
      state.methods = (data && data.methods) || [];
      renderMethods();
      return state.methods;
    }).catch(function () {
      state.methods = [];
      renderMethods();
      return [];
    });
  }

  function renderMethods() {
    const wrap = qs('#paySavedMethodsWrap');
    const list = qs('#paySavedMethods');
    if (!wrap || !list) return;
    list.innerHTML = '';

    if (!state.methods || state.methods.length === 0) {
      // No saved cards yet — hide the picker, default to new-card form.
      wrap.hidden = true;
      state.selectedMethodId = ADD_NEW_VALUE;
      applyMethodSelection();
      return;
    }
    wrap.hidden = false;

    // If the previously-selected method got deleted, fall back to
    // the newest saved card.
    const selectedExists = state.methods.some(function (m) {
      return m.methodId === state.selectedMethodId;
    });
    if (!selectedExists || state.selectedMethodId === ADD_NEW_VALUE) {
      state.selectedMethodId = state.methods[0].methodId;
    }

    state.methods.forEach(function (m) {
      const label = document.createElement('label');
      label.className = 'pay-method' + (m.methodId === state.selectedMethodId ? ' is-selected' : '');
      label.innerHTML =
        '<input type="radio" name="payMethod" value="' + escapeHtml(m.methodId) + '"' +
          (m.methodId === state.selectedMethodId ? ' checked' : '') + '>' +
        '<div class="pay-method-body">' +
          '<div class="pay-method-brand">' + escapeHtml(m.brand) + ' •••• ' + escapeHtml(m.last4) + '</div>' +
          '<div class="pay-method-meta">Expires ' +
            String(m.expMonth).padStart(2, '0') + '/' + String(m.expYear).slice(-2) +
            (m.nameOnCard ? ' · ' + escapeHtml(m.nameOnCard) : '') +
          '</div>' +
        '</div>' +
        '<button type="button" class="pay-method-remove" data-method-id="' + escapeHtml(m.methodId) + '">Remove</button>';
      list.appendChild(label);
    });

    // "Add a new card" row.
    const addNew = document.createElement('label');
    addNew.className = 'pay-method pay-method--addnew' +
      (state.selectedMethodId === ADD_NEW_VALUE ? ' is-selected' : '');
    addNew.innerHTML =
      '<input type="radio" name="payMethod" value="' + ADD_NEW_VALUE + '"' +
        (state.selectedMethodId === ADD_NEW_VALUE ? ' checked' : '') + '>' +
      '<div class="pay-method-body">' +
        '<div class="pay-method-brand">+ Add a new card</div>' +
        '<div class="pay-method-meta">Saved automatically for next time.</div>' +
      '</div>';
    list.appendChild(addNew);

    applyMethodSelection();
  }

  function applyMethodSelection() {
    const newCardFields = qs('#payNewCardFields');
    const showNew = state.selectedMethodId === ADD_NEW_VALUE;
    if (newCardFields) newCardFields.hidden = !showNew;
    // Re-mark which .pay-method has the selected state for the
    // visual highlight (CSS hover/checked alone isn't enough since
    // the radio inputs are inside the label and we want the
    // whole row tinted).
    document.querySelectorAll('.pay-method').forEach(function (el) {
      const radio = el.querySelector('input[type="radio"]');
      el.classList.toggle('is-selected', !!radio && radio.checked);
    });
  }

  function onMethodChange(e) {
    if (e.target && e.target.matches('input[name="payMethod"]')) {
      state.selectedMethodId = e.target.value;
      applyMethodSelection();
    }
  }

  function onMethodRemoveClick(e) {
    const btn = e.target.closest('.pay-method-remove');
    if (!btn) return;
    e.preventDefault();
    const methodId = btn.getAttribute('data-method-id');
    if (!methodId) return;
    if (!confirm('Remove this saved card?')) return;
    btn.disabled = true;
    api('/api/my-payment-methods/' + encodeURIComponent(methodId), {
      method: 'DELETE',
    }).then(function () {
      // Refresh the list. The render handles picking a new selection.
      return loadMethods();
    }).catch(function () {
      btn.disabled = false;
      showError("We couldn't remove that card. Please try again.");
    });
  }

  // ---------- Input formatting ----------
  function formatCardNumber(value) {
    const digits = String(value || '').replace(/\D/g, '').slice(0, 19);
    return digits.replace(/(\d{4})(?=\d)/g, '$1 ');
  }
  function formatExp(value) {
    const digits = String(value || '').replace(/\D/g, '').slice(0, 4);
    if (digits.length < 3) return digits;
    return digits.slice(0, 2) + '/' + digits.slice(2);
  }

  // ---------- Errors ----------
  function showError(msg) {
    const el = qs('#payError');
    if (!el) return;
    el.textContent = msg || "We couldn't process your payment. Please try again.";
    el.hidden = false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function clearError() {
    const el = qs('#payError');
    if (el) { el.hidden = true; el.textContent = ''; }
  }

  // ---------- Submit ----------
  function readForm() {
    const amount = parseFloat(String(qs('#payAmount').value || '').replace(/[^\d.]/g, ''));
    const cvv = String(qs('#payCvv').value || '').trim();
    const usingSaved = state.selectedMethodId && state.selectedMethodId !== ADD_NEW_VALUE;

    if (usingSaved) {
      return {
        amount: amount, cvv: cvv,
        paymentMethodId: state.selectedMethodId,
        loanId: state.loan && state.loan.id,
        usingSaved: true,
      };
    }

    const cardNumber = String(qs('#payCardNumber').value || '').replace(/\s+/g, '');
    const expDigits = String(qs('#payExp').value || '').replace(/\D/g, '');
    const expMonth = parseInt(expDigits.slice(0, 2), 10);
    const expYearShort = parseInt(expDigits.slice(2, 4), 10);
    const expYear = isNaN(expYearShort) ? 0 : (2000 + expYearShort);
    const nameOnCard = String(qs('#payName').value || '').trim();
    const zip = String(qs('#payZip').value || '').trim();
    return {
      amount: amount, cvv: cvv,
      cardNumber: cardNumber,
      expMonth: expMonth, expYear: expYear,
      nameOnCard: nameOnCard, zip: zip,
      loanId: state.loan && state.loan.id,
      usingSaved: false,
    };
  }

  function validateForm(f) {
    if (!f.amount || isNaN(f.amount) || f.amount <= 0) return 'Please enter a valid amount.';
    if (f.amount > 5000) return 'Amount must be $5,000 or less.';
    if (!f.cvv || !/^\d{3,4}$/.test(f.cvv)) return 'Please enter the 3- or 4-digit CVV.';
    if (f.usingSaved) return null;
    if (!f.cardNumber || f.cardNumber.length < 13) return 'Please enter a valid card number.';
    if (!f.expMonth || f.expMonth < 1 || f.expMonth > 12) return 'Please enter a valid expiration month (01-12).';
    if (!f.expYear || f.expYear < 2026 || f.expYear > 2050) return 'Please enter a valid expiration year.';
    return null;
  }

  function submitPayment(e) {
    if (e) e.preventDefault();
    if (state.submitting) return;
    clearError();

    const form = readForm();
    const err = validateForm(form);
    if (err) { showError(err); return; }

    state.initialBalance = state.loan ? Number(state.loan.balance) : null;
    const btn = qs('#payChargeBtn');
    state.submitting = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Processing payment…';
    }

    const reqBody = form.usingSaved
      ? {
          amount: form.amount,
          paymentMethodId: form.paymentMethodId,
          cvv: form.cvv,
          loanId: form.loanId,
        }
      : {
          amount: form.amount,
          cardNumber: form.cardNumber,
          expMonth: form.expMonth,
          expYear: form.expYear,
          cvv: form.cvv,
          nameOnCard: form.nameOnCard,
          zip: form.zip,
          loanId: form.loanId,
        };

    api('/api/my-payment/charge', { method: 'POST', body: reqBody })
      .then(function (res) {
        if (res && res.success && res.transactionId) {
          const paid = Number(res.authAmount || form.amount);
          const receipt = {
            amount:        paid,
            last4:         res.last4 || form.last4 || '',
            brand:         res.brand || form.brand || '',
            transactionId: res.transactionId,
            when:          Date.now(),
          };
          sessionStorage.setItem(SUCCESS_KEY, JSON.stringify(receipt));
          // Best-effort balance refresh — we don't display the new
          // balance on the receipt anymore (it can be misleading right
          // after a payment posts), so failures don't matter.
          return loadLoan()
            .catch(function () {})
            .then(function () { showReceipt(receipt); });
        }
        const reason = (res && res.resultText) || 'Card declined.';
        showError(reason + ' Please try a different card or call (747) 270-7121.');
      })
      .catch(function (e) {
        let msg = "We couldn't process your payment.";
        const errBody = e && e.body;
        if (errBody && typeof errBody === 'object') {
          const code = errBody.error || errBody.code || '';
          msg = {
            invalid_amount:           'Please enter a valid amount.',
            amount_out_of_range:      'Amount must be between $0.01 and $5,000.',
            invalid_card_number:      'Card number is invalid.',
            card_failed_luhn:         'Card number is invalid — please double-check.',
            invalid_expiry:           'Expiration is invalid.',
            invalid_exp_month:        'Expiration month is invalid.',
            invalid_exp_year:         'Expiration year is invalid.',
            invalid_cvv:              'CVV is invalid.',
            payment_method_not_found: 'That saved card is no longer available. Please add a new card.',
            repay_creds_missing:      'Payments are temporarily unavailable. Please call (747) 270-7121.',
            repay_creds_incomplete:   'Payments are temporarily unavailable. Please call (747) 270-7121.',
            repay_http_error:         'Our payment processor returned an error. Please try again or call (747) 270-7121.',
          }[code] || msg;
        }
        showError(msg);
      })
      .then(function () {
        state.submitting = false;
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Pay now';
        }
      });
  }

  function showReceipt(receipt) {
    const amount = Number(receipt && receipt.amount) || 0;
    const last4  = (receipt && receipt.last4) || '';
    const brand  = (receipt && receipt.brand) || '';
    const txId   = (receipt && receipt.transactionId) || '';
    const when   = (receipt && receipt.when) || Date.now();

    qs('#payFormCard').hidden = true;
    // Amount split across two spans so the "$" sits smaller than the
    // number — matches the dashboard's hero-balance typography.
    setText(qs('[data-receipt-amount]'),
      amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','));

    // "Visa ending 5556" — graceful when fields are missing.
    let cardLine = '—';
    if (brand && last4) {
      cardLine = brand + ' ending ' + last4;
    } else if (last4) {
      cardLine = 'Card ending ' + last4;
    } else if (brand) {
      cardLine = brand;
    }
    setText(qs('[data-receipt-card]'), cardLine);

    // Human-readable timestamp in the customer's locale.
    let dateLine = '—';
    try {
      const d = new Date(when);
      dateLine = d.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
      }) + ' at ' + d.toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit',
      });
    } catch (e) { /* keep fallback */ }
    setText(qs('[data-receipt-date]'), dateLine);

    setText(qs('[data-receipt-confirmation]'), String(txId || '—'));

    qs('#payReceipt').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // "Make another payment" — reset the form state and return to the
  // pay card. Saved-card list reloads in case any state has changed.
  function resetForPayAgain() {
    qs('#payReceipt').hidden = true;
    const amt = qs('#payAmount'); if (amt) amt.value = '';
    const cvv = qs('#payCvv');    if (cvv) cvv.value = '';
    const num = qs('#payCardNumber'); if (num) num.value = '';
    const exp = qs('#payExp'); if (exp) exp.value = '';
    const nm  = qs('#payName'); if (nm)  nm.value  = '';
    const zip = qs('#payZip'); if (zip) zip.value = '';
    const err = qs('#payError'); if (err) { err.hidden = true; err.textContent = ''; }
    qs('#payFormCard').hidden = false;
    if (typeof loadSavedMethods === 'function') {
      try { loadSavedMethods(); } catch (e) { /* non-fatal */ }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    const form = qs('#payChargeForm');
    if (form) form.addEventListener('submit', submitPayment);

    const methodsList = qs('#paySavedMethods');
    if (methodsList) {
      methodsList.addEventListener('change', onMethodChange);
      methodsList.addEventListener('click', onMethodRemoveClick);
    }

    const payAgain = qs('#payAgainBtn');
    if (payAgain) payAgain.addEventListener('click', resetForPayAgain);

    // Live formatting.
    const cardInput = qs('#payCardNumber');
    if (cardInput) cardInput.addEventListener('input', function () {
      this.value = formatCardNumber(this.value);
    });
    const expInput = qs('#payExp');
    if (expInput) expInput.addEventListener('input', function () {
      this.value = formatExp(this.value);
    });
    const cvvInput = qs('#payCvv');
    if (cvvInput) cvvInput.addEventListener('input', function () {
      this.value = (this.value || '').replace(/\D/g, '').slice(0, 4);
    });
    const zipInput = qs('#payZip');
    if (zipInput) zipInput.addEventListener('input', function () {
      this.value = (this.value || '').replace(/\D/g, '').slice(0, 5);
    });
    const amtInput = qs('#payAmount');
    if (amtInput) amtInput.addEventListener('blur', function () {
      const v = parseFloat(String(this.value || '').replace(/[^\d.]/g, ''));
      if (!isNaN(v) && v > 0) this.value = v.toFixed(2);
    });

    // Load loan + methods in parallel.
    const loanP = loadLoan();
    const methodsP = loadMethods();

    Promise.all([loanP, methodsP]).then(function (results) {
      const loan = results[0];
      const formCard = qs('#payFormCard');
      if (formCard) formCard.hidden = !loan;
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      showError('Could not load your loan details. Please refresh the page.');
    });
  });
})();
