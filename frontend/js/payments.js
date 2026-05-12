/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller (Path 1 / direct-charge).

   The customer enters their card + amount in OUR portal; we POST
   to /api/my-payment/charge which calls Repay's RgAPI REST endpoint
   directly (no Vergent handoff).

   Why direct-charge: Vergent's customer-portal payment routes
   reject our handoff redirects and their /V1/PostCustomerLoanPayment
   API is broken for our tenant (full archeology in
   handlers/payments.py docstring). Direct Repay charge sidesteps
   both — money moves, we record the transaction in our own DDB
   ledger, Vergent reconciliation is best-effort.
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
      // Pre-fill the amount field with the next-due (or balance) so
      // the customer can pay in one click without typing.
      const amountInput = qs('#payAmount');
      if (amountInput && !amountInput.value) {
        const preset = Number(loan.nextDueAmount || loan.balance || 0);
        if (preset > 0) {
          amountInput.value = preset.toFixed(2);
        }
      }
      return loan;
    });
  }

  // ---------- Form input helpers (card number / exp formatting) ----------
  function formatCardNumber(value) {
    // Strip non-digits, group in 4s. Max 19 digits (Visa/MC/Discover
    // are 16; Amex 15; Diners 14; some others up to 19).
    const digits = String(value || '').replace(/\D/g, '').slice(0, 19);
    return digits.replace(/(\d{4})(?=\d)/g, '$1 ');
  }
  function formatExp(value) {
    // MM/YY auto-insert. Strip non-digits, slash after 2 digits.
    const digits = String(value || '').replace(/\D/g, '').slice(0, 4);
    if (digits.length < 3) return digits;
    return digits.slice(0, 2) + '/' + digits.slice(2);
  }

  // ---------- Charge ----------
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

  function readForm() {
    const amount = parseFloat(String(qs('#payAmount').value || '').replace(/[^\d.]/g, ''));
    const cardNumber = String(qs('#payCardNumber').value || '').replace(/\s+/g, '');
    const expRaw = String(qs('#payExp').value || '');
    const expDigits = expRaw.replace(/\D/g, '');
    const expMonth = parseInt(expDigits.slice(0, 2), 10);
    const expYearShort = parseInt(expDigits.slice(2, 4), 10);
    const expYear = isNaN(expYearShort) ? 0 : (2000 + expYearShort);
    const cvv = String(qs('#payCvv').value || '').trim();
    const nameOnCard = String(qs('#payName').value || '').trim();
    const zip = String(qs('#payZip').value || '').trim();
    return {
      amount: amount,
      cardNumber: cardNumber,
      expMonth: expMonth,
      expYear: expYear,
      cvv: cvv,
      nameOnCard: nameOnCard,
      zip: zip,
      loanId: state.loan && state.loan.id,
    };
  }

  function validateForm(f) {
    if (!f.amount || isNaN(f.amount) || f.amount <= 0) return 'Please enter a valid amount.';
    if (f.amount > 5000) return 'Amount must be $5,000 or less.';
    if (!f.cardNumber || f.cardNumber.length < 13) return 'Please enter a valid card number.';
    if (!f.expMonth || f.expMonth < 1 || f.expMonth > 12) return 'Please enter a valid expiration month (01-12).';
    if (!f.expYear || f.expYear < 2026 || f.expYear > 2050) return 'Please enter a valid expiration year.';
    if (f.cvv && !/^\d{3,4}$/.test(f.cvv)) return 'CVV must be 3 or 4 digits.';
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

    api('/api/my-payment/charge', {
      method: 'POST',
      body: {
        amount: form.amount,
        cardNumber: form.cardNumber,
        expMonth: form.expMonth,
        expYear: form.expYear,
        cvv: form.cvv,
        nameOnCard: form.nameOnCard,
        zip: form.zip,
        loanId: form.loanId,
      },
    }).then(function (res) {
      if (res && res.success && res.transactionId) {
        // Approved — refresh balance + show receipt.
        sessionStorage.setItem(SUCCESS_KEY, JSON.stringify({
          amount: Number(res.authAmount || form.amount),
          last4: res.last4 || '',
          brand: res.brand || '',
          transactionId: res.transactionId,
          when: Date.now(),
        }));
        return loadLoan().then(function (loan) {
          const newBal = loan ? Number(loan.balance) : null;
          showReceipt(Number(res.authAmount || form.amount), newBal);
        }).catch(function () {
          showReceipt(Number(res.authAmount || form.amount), null);
        });
      }
      // success:false → declined.
      const reason = (res && res.resultText) || 'Card declined.';
      showError(reason + ' Please try a different card or call (747) 270-7121.');
    }).catch(function (e) {
      let msg = "We couldn't process your payment.";
      const errBody = e && e.body;
      if (errBody && typeof errBody === 'object') {
        const code = errBody.error || errBody.code || '';
        msg = {
          invalid_amount:         'Please enter a valid amount.',
          amount_out_of_range:    'Amount must be between $0.01 and $5,000.',
          invalid_card_number:    'Card number is invalid.',
          card_failed_luhn:       'Card number is invalid — please double-check.',
          invalid_expiry:         'Expiration is invalid.',
          invalid_exp_month:      'Expiration month is invalid.',
          invalid_exp_year:       'Expiration year is invalid.',
          invalid_cvv:            'CVV is invalid.',
          repay_creds_missing:    'Payments are temporarily unavailable. Please call (747) 270-7121.',
          repay_creds_incomplete: 'Payments are temporarily unavailable. Please call (747) 270-7121.',
          repay_http_error:       'Our payment processor returned an error. Please try again or call (747) 270-7121.',
        }[code] || msg;
      }
      showError(msg);
    }).then(function () {
      state.submitting = false;
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Pay now';
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
    const form = qs('#payChargeForm');
    if (form) form.addEventListener('submit', submitPayment);

    // Live formatting for card number + expiry.
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

    loadLoan().then(function (loan) {
      const formCard = qs('#payFormCard');
      if (formCard) formCard.hidden = !loan;
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      showError('Could not load your loan details. Please refresh the page.');
    });
  });
})();
