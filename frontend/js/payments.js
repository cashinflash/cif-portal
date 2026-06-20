/* ═══════════════════════════════════════
   CASH IN FLASH — Payments page controller.

   Pay:  pick a saved Vergent card → enter amount + CVV → Pay now.
         POST /api/my-payment/charge {useCardAuto, cardId, amount, cvv, loanId};
         Vergent charges the card natively (Card Auto) and posts to the loan.

   Add a card:  "+ Add a debit card" opens a modal → enter card → Save card.
         POST /api/my-cards; the backend tokenizes at Repay and saves the card
         to the customer's Vergent profile. It then appears in the saved-card
         list and is payable via the flow above. The PAN is never stored by us.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  const TOKEN_KEY = 'cif_id_token';
  const LOGIN_URL = '/login.html';
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
    bankAccounts: [],
    selectedMethodId: null,
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
        // No active loan — surface the "Need extra cash?" cross-sell banner.
        var bannerEmpty = document.querySelector('.app-loan-banner');
        if (bannerEmpty) bannerEmpty.style.display = '';
        return null;
      }
      const loan = data.loan;
      state.loan = loan;
      // Gate the "Need extra cash?" banner: never offer a new loan while an
      // active loan with a balance is open.
      var hasActiveLoan = !!(loan && Number(loan.balance) > 0);
      var bannerActive = document.querySelector('.app-loan-banner');
      if (bannerActive) bannerActive.style.display = hasActiveLoan ? 'none' : '';
      setText(qs('[data-pay-loan-id]', card), '#' + (loan.publicId || loan.id || '—'));
      setText(qs('[data-pay-balance]', card), money(loan.balance).replace(/^\$/, ''));
      const caption = qs('[data-pay-caption]', card);
      if (caption) {
        // In the redesigned card this value sits under the "Due date" label,
        // so show just the date (the amount is already the big "Amount due").
        caption.textContent = loan.nextDueDate ? formatDate(loan.nextDueDate) : '—';
      }
      const pill = qs('[data-pay-loan-status]', card);
      if (pill) {
        // Match the Home card: "In good standing" for a current loan, red past-due otherwise.
        var st = (loan.status || '').toLowerCase();
        var isPast = st.indexOf('past') !== -1 || st.indexOf('late') !== -1 || st.indexOf('delinq') !== -1;
        pill.textContent = isPast ? (loan.status || 'Past due') : 'In good standing';
        pill.classList.toggle('dash-pill--past-due', isPast);
      }
      // Payment breakdown (defensive — every element is optional). Total is
      // the balance; principal/fee are shown only when the API surfaces them,
      // otherwise they stay as an em-dash placeholder (do NOT overwrite with
      // a wrong value).
      const totalEl = qs('[data-pay-total]');
      if (totalEl) totalEl.textContent = money(loan.balance);
      const principal = (loan.principal != null ? loan.principal
        : (loan.principalBalance != null ? loan.principalBalance : null));
      if (principal != null) setText(qs('[data-pay-principal]'), money(principal));
      const fee = (loan.fees != null ? loan.fees
        : (loan.fee != null ? loan.fee
        : (loan.loanFee != null ? loan.loanFee : null)));
      if (fee != null) setText(qs('[data-pay-fee]'), money(fee));
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

  // ---------- Saved methods (from the customer's Vergent profile) ----------
  function loadMethods() {
    return api('/api/my-cards').then(function (data) {
      var cards = (data && data.cards) || [];
      var mapped = cards
        .filter(function (c) { return c && c.id; })
        .map(function (c) {
          return {
            methodId:      'v:' + c.id,
            vergentCardId: c.id,
            brand:         c.brand || 'Card',
            last4:         c.last4 || '',
            expMonth:      c.expMonth || '',
            expYear:       c.expYear || '',
            nameOnCard:    c.nameOnCard || '',
          };
        });
      // De-dupe by last 4: repeated saves of the same physical card create
      // several Vergent card rows; show one entry per card (any of those
      // rows charges the same card via Card Auto, so we keep the first).
      var seen = {};
      state.methods = [];
      mapped.forEach(function (m) {
        var key = m.last4 || m.methodId;
        if (seen[key]) return;
        seen[key] = true;
        state.methods.push(m);
      });
      renderMethods();
      return state.methods;
    }).catch(function () {
      state.methods = [];
      renderMethods();
      return [];
    });
  }

  // Mirror the green active-loan card's "Repayment method" line to the
  // selected card (fallback: first method), formatted like the Home page.
  // Leaves the "Card on file" fallback when there are no saved methods.
  function updateRepayLabel() {
    var els = document.querySelectorAll('[data-pay-repay-method]');
    if (!els.length || !state.methods || !state.methods.length) return;
    var sel = state.methods.filter(function (m) { return m.methodId === state.selectedMethodId; })[0] || state.methods[0];
    if (sel) {
      var label = (sel.brand || 'Card') + ' •• ' + (sel.last4 || '');
      els.forEach(function (el) { el.textContent = label; });
    }
  }

  function renderMethods() {
    const list = qs('#paySavedMethods');
    const noCards = qs('#payNoCardsHint');
    if (!list) return;
    list.innerHTML = '';

    if (!state.methods || state.methods.length === 0) {
      state.selectedMethodId = null;
      if (noCards) noCards.hidden = false;
      applyMethodSelection();
      return;
    }
    if (noCards) noCards.hidden = true;

    // Keep the current selection if it still exists, else select the first.
    const selectedExists = state.methods.some(function (m) {
      return m.methodId === state.selectedMethodId;
    });
    if (!selectedExists) state.selectedMethodId = state.methods[0].methodId;

    state.methods.forEach(function (m, idx) {
      const label = document.createElement('label');
      // Only the first (default) card shows by default; the rest stay in the
      // DOM but hidden behind "View more" so the block stays compact. They
      // remain fully selectable once revealed — the radio logic is untouched.
      label.className = 'pay-method' +
        (m.methodId === state.selectedMethodId ? ' is-selected' : '') +
        (idx > 0 ? ' pay-method--hidden' : '');
      label.innerHTML =
        '<input type="radio" name="payMethod" value="' + escapeHtml(m.methodId) + '"' +
          (m.methodId === state.selectedMethodId ? ' checked' : '') + '>' +
        '<span class="pay-method-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg></span>' +
        '<div class="pay-method-body">' +
          '<div class="pay-method-brand">' + escapeHtml(m.brand) + ' •••• ' + escapeHtml(m.last4) + '</div>' +
          '<div class="pay-method-meta">Expires ' +
            String(m.expMonth).padStart(2, '0') + '/' + String(m.expYear).slice(-2) +
            (m.nameOnCard ? ' · ' + escapeHtml(m.nameOnCard) : '') +
          '</div>' +
        '</div>' +
        (idx === 0 ? '<span class="pay-method-default">Default</span>' : '');
      list.appendChild(label);
    });

    // "View more (N)" toggle — reveals the hidden cards. All cards stay
    // selectable; this is purely a show/hide of rows already in the DOM.
    if (state.methods.length > 1) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'pay-viewmore';
      const hiddenCount = state.methods.length - 1;
      more.textContent = 'View more (' + hiddenCount + ')';
      more.addEventListener('click', function () {
        const hidden = list.querySelectorAll('.pay-method.pay-method--hidden');
        if (hidden.length) {
          hidden.forEach(function (el) { el.classList.remove('pay-method--hidden'); });
          more.textContent = 'Show less';
        } else {
          // Re-hide every card after the first.
          list.querySelectorAll('.pay-method').forEach(function (el, idx) {
            if (idx > 0) el.classList.add('pay-method--hidden');
          });
          more.textContent = 'View more (' + hiddenCount + ')';
        }
      });
      list.appendChild(more);
    }

    updateRepayLabel();
    applyMethodSelection();
  }

  // ---------- Bank accounts (pay-from-checking) ----------
  // Placeholder loader — wired to set an empty list for now so the group
  // renders its "no bank account on file" row. Plug-and-play once the API
  // lands.
  function loadBankAccounts() {
    state.bankAccounts = [];
    // TODO: wire to bank-accounts API
    renderBankAccounts();
    return Promise.resolve(state.bankAccounts);
  }

  // Non-selectable bank-account rows (chevron instead of radio). When there
  // are no accounts we show ONE muted placeholder row — never a fake account.
  function renderBankAccounts() {
    const list = qs('#payBankAccounts');
    if (!list) return;
    list.innerHTML = '';

    const bankSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="21" x2="21" y2="21"/><line x1="3" y1="10" x2="21" y2="10"/><polyline points="5 6 12 3 19 6"/><line x1="4" y1="10" x2="4" y2="21"/><line x1="20" y1="10" x2="20" y2="21"/><line x1="8" y1="10" x2="8" y2="21"/><line x1="12" y1="10" x2="12" y2="21"/><line x1="16" y1="10" x2="16" y2="21"/></svg>';
    const chevron = '<span class="pay-method-bankchev" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg></span>';

    if (!state.bankAccounts || state.bankAccounts.length === 0) {
      const row = document.createElement('div');
      row.className = 'pay-method pay-method-bank is-placeholder';
      row.innerHTML =
        '<span class="pay-method-icon" aria-hidden="true">' + bankSvg + '</span>' +
        '<div class="pay-method-body">' +
          '<div class="pay-method-brand">No bank account on file</div>' +
          '<div class="pay-method-meta">Link a bank account to pay from your checking</div>' +
        '</div>' +
        chevron;
      list.appendChild(row);
      return;
    }

    state.bankAccounts.forEach(function (b, idx) {
      const row = document.createElement('div');
      row.className = 'pay-method pay-method-bank';
      const acctType = b.accountType || b.type || 'Checking';
      const last4 = b.last4 || b.mask || '';
      const bankName = b.bankName || b.institution || b.name || '';
      const isDefault = (b.isDefault === true) || (idx === 0 && b.isDefault !== false);
      row.innerHTML =
        '<span class="pay-method-icon" aria-hidden="true">' + bankSvg + '</span>' +
        '<div class="pay-method-body">' +
          '<div class="pay-method-brand">' + escapeHtml(acctType) +
            (last4 ? ' •••• ' + escapeHtml(last4) : '') + '</div>' +
          '<div class="pay-method-meta">' + escapeHtml(bankName) + '</div>' +
        '</div>' +
        (isDefault ? '<span class="pay-method-default">Default</span>' : '') +
        chevron;
      list.appendChild(row);
    });
  }

  function applyMethodSelection() {
    const btn = qs('#payChargeBtn');
    const hasCard = !!state.selectedMethodId;
    if (btn && !state.submitting) {
      btn.disabled = !hasCard;
      // Show the amount in the button label when we know it (from the amount
      // field, falling back to the loan balance). Falls back to plain
      // "Pay now" if neither is a positive number.
      var amtRaw = qs('#payAmount') && qs('#payAmount').value;
      var amt = parseFloat(String(amtRaw || '').replace(/[^\d.]/g, ''));
      if ((!amt || isNaN(amt) || amt <= 0) && state.loan) amt = Number(state.loan.balance);
      btn.textContent = (amt && !isNaN(amt) && amt > 0) ? ('Pay now ' + money(amt)) : 'Pay now';
    }
    document.querySelectorAll('.pay-method').forEach(function (el) {
      const radio = el.querySelector('input[type="radio"]');
      el.classList.toggle('is-selected', !!radio && radio.checked);
    });
    updateRepayLabel();
  }

  function onMethodChange(e) {
    if (e.target && e.target.matches('input[name="payMethod"]')) {
      state.selectedMethodId = e.target.value;
      applyMethodSelection();
    }
  }

  // ---------- Add-card modal ----------
  function openAddCard() {
    clearAddCardError();
    ['#payCardNumber', '#payExp', '#payName', '#payZip'].forEach(function (s) {
      const el = qs(s); if (el) el.value = '';
    });
    const modal = qs('#payAddCardModal');
    if (!modal) return;
    modal.hidden = false;
    requestAnimationFrame(function () { modal.classList.add('is-open'); });
    const first = qs('#payCardNumber');
    if (first) { try { first.focus(); } catch (e) { /* ignore */ } }
  }
  function closeAddCard() {
    const modal = qs('#payAddCardModal');
    if (!modal) return;
    modal.classList.remove('is-open');
    setTimeout(function () { modal.hidden = true; }, 180);
  }
  function showAddCardError(msg) {
    const el = qs('#payAddCardError');
    if (!el) return;
    el.textContent = msg || "We couldn't save that card. Please try again.";
    el.hidden = false;
  }
  function clearAddCardError() {
    const el = qs('#payAddCardError');
    if (el) { el.hidden = true; el.textContent = ''; }
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

  // ---------- Pay-form errors ----------
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

  // ---------- Read + validate ----------
  function readPayForm() {
    const amount = parseFloat(String(qs('#payAmount').value || '').replace(/[^\d.]/g, ''));
    const cvv = String(qs('#payCvv').value || '').trim();
    var sel = (state.methods || []).find(function (m) {
      return m.methodId === state.selectedMethodId;
    }) || {};
    return {
      amount: amount, cvv: cvv,
      vergentCardId: sel.vergentCardId,
      last4: sel.last4, brand: sel.brand,
      loanId: state.loan && state.loan.id,
    };
  }
  function validatePayForm(f) {
    if (!f.vergentCardId) return 'Please choose a saved card, or add one below.';
    if (!f.amount || isNaN(f.amount) || f.amount <= 0) return 'Please enter a valid amount.';
    if (f.amount > 5000) return 'Amount must be $5,000 or less.';
    if (!f.cvv || !/^\d{3,4}$/.test(f.cvv)) return 'Please enter the 3- or 4-digit CVV.';
    return null;
  }
  function readNewCard() {
    const cardNumber = String(qs('#payCardNumber').value || '').replace(/\s+/g, '');
    const expDigits = String(qs('#payExp').value || '').replace(/\D/g, '');
    const expMonth = parseInt(expDigits.slice(0, 2), 10);
    const expYearShort = parseInt(expDigits.slice(2, 4), 10);
    const expYear = isNaN(expYearShort) ? 0 : (2000 + expYearShort);
    return {
      cardNumber: cardNumber,
      expMonth: expMonth, expYear: expYear,
      nameOnCard: String(qs('#payName').value || '').trim(),
      zip: String(qs('#payZip').value || '').trim(),
    };
  }
  function validateNewCard(c) {
    if (!c.cardNumber || c.cardNumber.length < 13) return 'Please enter a valid card number.';
    if (!c.expMonth || c.expMonth < 1 || c.expMonth > 12) return 'Please enter a valid expiration month (01-12).';
    if (!c.expYear || c.expYear < 2026 || c.expYear > 2050) return 'Please enter a valid expiration year.';
    return null;
  }

  // ---------- Pay ----------
  function submitPayment(e) {
    if (e) e.preventDefault();
    if (state.submitting) return;
    clearError();

    const form = readPayForm();
    const err = validatePayForm(form);
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
        useCardAuto: true,
        cardId: form.vergentCardId,
        last4: form.last4,
        brand: form.brand,
        cvv: form.cvv,
        loanId: form.loanId,
      },
    })
      .then(function (res) {
        // STRICT success gate — only show the receipt when the backend
        // explicitly says success AND we have a real transaction id.
        if (res && res.success === true && res.transactionId) {
          const paid = Number(res.authAmount || form.amount);
          const receipt = {
            amount:        paid,
            last4:         res.last4 || form.last4 || '',
            brand:         res.brand || form.brand || '',
            transactionId: res.transactionId,
            when:          Date.now(),
          };
          sessionStorage.setItem(SUCCESS_KEY, JSON.stringify(receipt));
          return loadLoan()
            .catch(function () {})
            .then(function () { showReceipt(receipt); });
        }
        // Decline — surface the issuer's exact reason on the decline page.
        showDecline({
          reason: (res && res.resultText) || 'Card declined.',
          amount: form.amount,
          last4:  form.last4 || (res && res.last4) || '',
          brand:  form.brand || (res && res.brand) || 'Card',
        });
      })
      .catch(function (e2) {
        const errBody = (e2 && e2.body) || {};
        const code = errBody.error || errBody.code || '';
        const inlineMsgs = {
          invalid_amount:           'Please enter a valid amount.',
          amount_out_of_range:      'Amount must be between $0.01 and $5,000.',
          invalid_cvv:              'CVV is invalid.',
          missing_loan_or_card:     'Please pick a saved card.',
          invalid_cardauto_params:  'Please pick a saved card.',
          card_not_owned:           'That card isn’t on your account. Please pick one of your saved cards.',
          loan_not_owned:           'We couldn’t match that to your loan. Please refresh and try again.',
        };
        if (inlineMsgs[code]) { showError(inlineMsgs[code]); return; }
        showDecline({
          reason: errBody.resultText
                || 'We couldn\'t reach the payment processor. Please try again.',
          amount: form.amount,
          last4:  form.last4 || '',
          brand:  form.brand || 'Card',
        });
      })
      .then(function () {
        state.submitting = false;
        if (btn) { btn.disabled = false; }
        applyMethodSelection();
      });
  }

  // ---------- Save a new card (from the modal) ----------
  function saveCard(e) {
    if (e) e.preventDefault();
    if (state.submitting) return;
    clearAddCardError();

    const card = readNewCard();
    const err = validateNewCard(card);
    if (err) { showAddCardError(err); return; }

    const btn = qs('#payAddCardSave');
    state.submitting = true;
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

    api('/api/my-cards', {
      method: 'POST',
      body: {
        cardNumber: card.cardNumber,
        expMonth:   card.expMonth,
        expYear:    card.expYear,
        nameOnCard: card.nameOnCard,
        zip:        card.zip,
      },
    })
      .then(function (res) {
        const newLast4 = (res && res.last4) || '';
        // Never keep the PAN in the DOM after a successful save.
        ['#payCardNumber', '#payExp', '#payName', '#payZip'].forEach(function (s) {
          const el = qs(s); if (el) el.value = '';
        });
        // Reload from Vergent, select the new card, close the modal.
        return loadMethods().then(function (methods) {
          var match = (methods || []).find(function (m) {
            return newLast4 && m.last4 === newLast4;
          });
          state.selectedMethodId = match ? match.methodId
            : (methods && methods.length ? methods[0].methodId : null);
          renderMethods();
          closeAddCard();
          showCardAdded(newLast4);
        });
      })
      .catch(function (e2) {
        const code = (e2 && e2.body && (e2.body.error || e2.body.code)) || '';
        const msgs = {
          invalid_card_number: 'Card number is invalid.',
          card_failed_luhn:    'Card number is invalid — please double-check it.',
          invalid_exp_month:   'Expiration month is invalid.',
          invalid_exp_year:    'Expiration year is invalid.',
          tokenize_failed:     'We couldn’t verify that card. Please double-check the details and try again.',
          vergent_save_failed: 'We couldn’t save that card right now. Please try again in a moment.',
        };
        showAddCardError(msgs[code] || 'We couldn’t save that card. Please try again.');
      })
      .then(function () {
        state.submitting = false;
        if (btn) { btn.disabled = false; btn.textContent = 'Save card'; }
        applyMethodSelection();
      });
  }

  function showCardAdded(last4) {
    const el = qs('#payCardAddedNote');
    if (!el) return;
    el.textContent = last4
      ? ('Card ending ' + last4 + ' added. Enter an amount and pay below.')
      : 'Card added to your account. Enter an amount and pay below.';
    el.hidden = false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function showReceipt(receipt) {
    const amount = Number(receipt && receipt.amount) || 0;
    const last4  = (receipt && receipt.last4) || '';
    const brand  = (receipt && receipt.brand) || '';
    const txId   = (receipt && receipt.transactionId) || '';
    const when   = (receipt && receipt.when) || Date.now();

    qs('#payFormCard').hidden = true;
    setText(qs('[data-receipt-amount]'),
      amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','));

    let cardLine = '—';
    if (brand && last4) cardLine = brand + ' ending ' + last4;
    else if (last4)     cardLine = 'Card ending ' + last4;
    else if (brand)     cardLine = brand;
    setText(qs('[data-receipt-card]'), cardLine);

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

  // Decline view — surfaces the issuer's exact decline reason; never shows
  // a fake success, and reassures the customer their loan was NOT charged.
  function showDecline(info) {
    info = info || {};
    var reason = String(info.reason || 'Card declined.').trim();
    var html = reason.split(/\s*;\s+/)
      .map(function (line) { return escapeHtml(line); })
      .join('<br>');
    var reasonEl = qs('#payDeclineReason');
    if (reasonEl) reasonEl.innerHTML = html;

    var brand = info.brand || 'Card';
    var last4 = info.last4 || '';
    var cardLine = '—';
    if (brand && last4) cardLine = brand + ' ending ' + last4;
    else if (last4)     cardLine = 'Card ending ' + last4;
    else if (brand)     cardLine = brand;
    setText(qs('[data-decline-card]'), cardLine);

    var amount = Number(info.amount || 0);
    setText(qs('[data-decline-amount]'),
      '$' + amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','));

    qs('#payFormCard').hidden = true;
    qs('#payReceipt').hidden = true;
    qs('#payDecline').hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // "Make another payment" / "Try a different card" — reset to the pay card.
  function resetForPayAgain() {
    var decline = qs('#payDecline'); if (decline) decline.hidden = true;
    qs('#payReceipt').hidden = true;
    const amt = qs('#payAmount'); if (amt) amt.value = '';
    const cvv = qs('#payCvv');    if (cvv) cvv.value = '';
    const err = qs('#payError'); if (err) { err.hidden = true; err.textContent = ''; }
    const note = qs('#payCardAddedNote'); if (note) { note.hidden = true; note.textContent = ''; }
    qs('#payFormCard').hidden = false;
    loadMethods();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------- Boot ----------
  document.addEventListener('DOMContentLoaded', function () {
    const form = qs('#payChargeForm');
    if (form) form.addEventListener('submit', submitPayment);

    const methodsList = qs('#paySavedMethods');
    if (methodsList) methodsList.addEventListener('change', onMethodChange);

    // Add-card modal wiring.
    const addBtn = qs('#payAddCardBtn');
    if (addBtn) addBtn.addEventListener('click', openAddCard);
    const addForm = qs('#payAddCardForm');
    if (addForm) addForm.addEventListener('submit', saveCard);
    const addCancel = qs('#payAddCardCancel');
    if (addCancel) addCancel.addEventListener('click', closeAddCard);
    const addBackdrop = qs('#payAddCardBackdrop');
    if (addBackdrop) addBackdrop.addEventListener('click', closeAddCard);
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        const modal = qs('#payAddCardModal');
        if (modal && !modal.hidden) closeAddCard();
      }
    });

    const payAgain = qs('#payAgainBtn');
    if (payAgain) payAgain.addEventListener('click', resetForPayAgain);
    const tryAgain = qs('#payTryAgainBtn');
    if (tryAgain) tryAgain.addEventListener('click', resetForPayAgain);

    // Live formatting (the card inputs live in the modal).
    const cardInput = qs('#payCardNumber');
    if (cardInput) cardInput.addEventListener('input', function () { this.value = formatCardNumber(this.value); });
    const expInput = qs('#payExp');
    if (expInput) expInput.addEventListener('input', function () { this.value = formatExp(this.value); });
    const zipInput = qs('#payZip');
    if (zipInput) zipInput.addEventListener('input', function () { this.value = (this.value || '').replace(/\D/g, '').slice(0, 5); });
    const cvvInput = qs('#payCvv');
    if (cvvInput) cvvInput.addEventListener('input', function () { this.value = (this.value || '').replace(/\D/g, '').slice(0, 4); });
    const amtInput = qs('#payAmount');
    if (amtInput) amtInput.addEventListener('blur', function () {
      const v = parseFloat(String(this.value || '').replace(/[^\d.]/g, ''));
      if (!isNaN(v) && v > 0) this.value = v.toFixed(2);
      // Keep the Pay-now button label ($amount) in sync with the field.
      applyMethodSelection();
    });

    // Load loan + methods in parallel.
    const loanP = loadLoan();
    const methodsP = loadMethods();
    loadBankAccounts();
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
