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
  // Bank (ACH) payments are pending for ~5 business days — tracked
  // separately from the instant card-success banner.
  const ACH_PENDING_KEY = 'cif_ach_pending';

  // US Federal Reserve / bank holidays — ACH doesn't settle on these or on
  // weekends. Keep in sync with _US_BANK_HOLIDAYS in handlers/payments.py.
  const US_BANK_HOLIDAYS = [
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-05-25', '2026-06-19',
    '2026-07-03', '2026-09-07', '2026-10-12', '2026-11-11', '2026-11-26',
    '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15', '2027-05-31',
    '2027-06-18', '2027-07-05', '2027-09-06', '2027-10-11', '2027-11-11',
    '2027-11-25', '2027-12-24',
  ];
  function _ymd(d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }
  // The date `n` banking days from today (skips weekends + Fed holidays).
  function addBusinessDays(n) {
    var d = new Date();
    var added = 0;
    while (added < n) {
      d.setDate(d.getDate() + 1);
      var dow = d.getDay();
      if (dow === 0 || dow === 6) continue;
      if (US_BANK_HOLIDAYS.indexOf(_ymd(d)) !== -1) continue;
      added++;
    }
    return _ymd(d);
  }

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

  function daysPastDue(loan) {
    if (!loan || !loan.nextDueDate) return 0;
    var due = new Date(loan.nextDueDate);
    if (isNaN(due.getTime())) return 0;
    var t = new Date();
    var a = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
    var b = Date.UTC(t.getFullYear(), t.getMonth(), t.getDate());
    var d = Math.round((b - a) / 86400000);
    return d > 0 ? d : 0;
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
    selectedBankId: null,
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
        card.classList.add('loan-card--paidup');
        if (body) body.hidden = true;
        if (empty) empty.hidden = false;
        // No active loan — surface the "Need extra cash?" cross-sell banner.
        var bannerEmpty = document.querySelector('.app-loan-banner');
        if (bannerEmpty) bannerEmpty.style.display = '';
        return null;
      }
      const loan = data.loan;
      card.classList.remove('loan-card--art', 'loan-card--paidup');
      state.loan = loan;
      // Gate the "Need extra cash?" banner: never offer a new loan while an
      // active loan with a balance is open.
      var hasActiveLoan = !!(loan && Number(loan.balance) > 0);
      var bannerActive = document.querySelector('.app-loan-banner');
      if (bannerActive) bannerActive.style.display = hasActiveLoan ? 'none' : '';
      setText(qs('[data-pay-loan-id]', card), (loan.publicId || loan.id || '—'));
      setText(qs('[data-pay-balance]', card), money(loan.balance));
      var _funded = (loan.principal != null ? loan.principal
        : (loan.principalBalance != null ? loan.principalBalance : null));
      setText(qs('[data-pay-funded]', card), _funded != null ? money(_funded) : '—');
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
        pill.textContent = isPast ? (loan.status || 'Past due') : 'Current';
        pill.classList.toggle('dash-pill--past-due', isPast);
      }
      // Bank (ACH) payment pending → "Processing" pill + estimated-clear strip.
      _applyAchPending(card, qs('[data-pay-loan-status]', card), loan);
      // Recolor the summary card by past-due severity (amber 1–4 days, red 5+),
      // matching Home — independent of the pill so it works even if absent.
      var _st = (loan.status || '').toLowerCase();
      var _past = _st.indexOf('past') !== -1 || _st.indexOf('late') !== -1 || _st.indexOf('delinq') !== -1;
      var _dpd = _past ? daysPastDue(loan) : 0;
      var _soft = _past && _dpd >= 1 && _dpd <= 4;
      card.classList.toggle('is-pastdue-soft', _soft);
      card.classList.toggle('is-pastdue', _past && !_soft);
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
    if (!els.length) return;
    // Bank (ACH) selected — show the bank account on the summary.
    if (state.selectedBankId) {
      var bank = (state.bankAccounts || []).filter(function (b) {
        return String(b.id) === String(state.selectedBankId);
      })[0];
      if (bank) {
        els.forEach(function (el) {
          el.textContent = (bank.accountType || 'Bank') + ' •• ' + (bank.last4 || '');
        });
        return;
      }
    }
    if (!state.methods || !state.methods.length) return;
    var sel = state.methods.filter(function (m) { return m.methodId === state.selectedMethodId; })[0] || state.methods[0];
    if (sel) {
      var label = (sel.brand || 'Card') + ' •• ' + (sel.last4 || '');
      els.forEach(function (el) { el.textContent = label; });
    }
  }

  // Card-network mark for the method circle. Recognizable, trademark-light
  // marks on a white chip; falls back to a generic card glyph.
  function brandIconHtml(brand) {
    var b = (brand || '').toLowerCase();
    if (b.indexOf('master') !== -1) {
      return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><svg width="28" height="18" viewBox="0 0 32 20"><circle cx="13" cy="10" r="8" fill="#EB001B"/><circle cx="19" cy="10" r="8" fill="#F79E1B" fill-opacity=".9"/></svg></span>';
    }
    if (b.indexOf('visa') !== -1) {
      return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><span style="color:#1A1F71;font-weight:800;font-style:italic;font-size:.66rem;letter-spacing:.3px">VISA</span></span>';
    }
    if (b.indexOf('amex') !== -1 || b.indexOf('american') !== -1) {
      return '<span class="pay-method-icon pay-brand-icon" style="background:#1F72CD;border-color:#1F72CD" aria-hidden="true"><span style="color:#fff;font-weight:800;font-size:.5rem;letter-spacing:.3px">AMEX</span></span>';
    }
    if (b.indexOf('discover') !== -1) {
      return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><span style="color:#E8850D;font-weight:800;font-size:.52rem;letter-spacing:.2px">DISC</span></span>';
    }
    return '<span class="pay-method-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg></span>';
  }

  // Shared "View more (N)" / "Show less" toggle for a method list (cards or
  // banks). Rows after the first carry .pay-method--hidden; this reveals them.
  function makeViewMore(list, hiddenCount) {
    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'pay-viewmore';
    more.textContent = 'View more (' + hiddenCount + ')';
    more.addEventListener('click', function () {
      var hidden = list.querySelectorAll('.pay-method.pay-method--hidden');
      if (hidden.length) {
        hidden.forEach(function (el) { el.classList.remove('pay-method--hidden'); });
        more.textContent = 'Show less';
      } else {
        list.querySelectorAll('.pay-method').forEach(function (el, idx) {
          if (idx > 0) el.classList.add('pay-method--hidden');
        });
        more.textContent = 'View more (' + hiddenCount + ')';
      }
    });
    return more;
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
        brandIconHtml(m.brand) +
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

    // "View more (N)" toggle — rendered into the actions row (left of the
    // Add button). All cards stay selectable; purely a show/hide of rows.
    const cardMoreSlot = qs('#payCardViewMore');
    if (cardMoreSlot) {
      cardMoreSlot.innerHTML = '';
      if (state.methods.length > 1) {
        cardMoreSlot.appendChild(makeViewMore(list, state.methods.length - 1));
      }
    }

    updateRepayLabel();
    applyMethodSelection();
  }

  // ---------- Bank accounts (on-file, from Vergent) ----------
  // Lists the customer's saved bank accounts (GET /api/my-banks → Vergent
  // GetCustomerBanks). Display-only for now; paying-by-bank (ACH) ships once
  // the PostBankPayment ReferralId/InstrumentId mapping is confirmed.
  function loadBankAccounts() {
    return api('/api/my-banks').then(function (data) {
      state.bankAccounts = (data && data.banks) || [];
      renderBankAccounts();
      return state.bankAccounts;
    }).catch(function () {
      state.bankAccounts = [];
      renderBankAccounts();
      return state.bankAccounts;
    });
  }

  // Map a bank name (from the FedACH directory) to its domain so we can show
  // its real logo. Covers the major US banks; the long tail falls back to the
  // colored monogram. Substring match on the normalized name.
  function bankDomain(name) {
    var n = (name || '').toUpperCase();
    var rules = [
      ['BANK OF AMERICA', 'bankofamerica.com'], ['WELLS FARGO', 'wellsfargo.com'],
      ['JPMORGAN', 'chase.com'], ['CHASE', 'chase.com'], ['CITIBANK', 'citi.com'],
      ['U.S. BANK', 'usbank.com'], ['US BANK', 'usbank.com'], ['USBANK', 'usbank.com'],
      ['PNC', 'pnc.com'], ['TRUIST', 'truist.com'], ['SUNTRUST', 'truist.com'],
      ['CAPITAL ONE', 'capitalone.com'], ['TD BANK', 'td.com'], ['CITIZENS', 'citizensbank.com'],
      ['FIFTH THIRD', '53.com'], ['KEYBANK', 'key.com'], ['KEY BANK', 'key.com'],
      ['REGIONS', 'regions.com'], ['HUNTINGTON', 'huntington.com'], ['M&T', 'mtb.com'],
      ['ALLY', 'ally.com'], ['USAA', 'usaa.com'], ['NAVY FEDERAL', 'navyfederal.org'],
      ['BMO', 'bmo.com'], ['HARRIS', 'bmo.com'], ['COMERICA', 'comerica.com'],
      ['DISCOVER', 'discover.com'], ['SCHWAB', 'schwab.com'], ['AMERICAN EXPRESS', 'americanexpress.com'],
      ['MARCUS', 'marcus.com'], ['GOLDMAN', 'marcus.com'], ['SOFI', 'sofi.com'],
      ['CHIME', 'chime.com'], ['VARO', 'varomoney.com'], ['GREEN DOT', 'greendot.com'],
      ['WOODFOREST', 'woodforest.com'], ['FIRST CITIZENS', 'firstcitizens.com'],
      ['SYNOVUS', 'synovus.com'], ['ZIONS', 'zionsbank.com'], ['FROST', 'frostbank.com'],
      ['FIRST HORIZON', 'firsthorizon.com'], ['VALLEY NATIONAL', 'valley.com'],
      ['WEBSTER', 'websterbank.com'], ['EAST WEST', 'eastwestbank.com'],
      ['SANTANDER', 'santanderbank.com'], ['FLAGSTAR', 'flagstar.com'],
      ['PENTAGON FEDERAL', 'penfed.org'], ['PENFED', 'penfed.org'],
      ['SCHOOLSFIRST', 'schoolsfirstfcu.org'], ['GOLDEN 1', 'golden1.com'],
      ['BECU', 'becu.org'], ['MORGAN STANLEY', 'morganstanley.com'],
    ];
    for (var i = 0; i < rules.length; i++) {
      if (n.indexOf(rules[i][0]) !== -1) return rules[i][1];
    }
    return '';
  }

  // Bank "logo" for the circle: the bank's favicon (actual logo) layered over a
  // colored monogram. The monogram shows instantly and stays as the fallback if
  // the favicon is blocked/missing — so it never shows a broken image.
  function bankMonoHtml(name) {
    var n = (name || 'Bank').trim();
    var letter = (n.charAt(0) || 'B').toUpperCase();
    var palette = ['#1a4d6b', '#0E8741', '#3b5bdb', '#7048e8', '#c2255c', '#e8590c', '#1098ad', '#2b8a3e'];
    var h = 0;
    for (var i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
    var domain = bankDomain(n);
    var logo = domain
      ? '<img class="pay-bank-logo" alt="" src="https://icons.duckduckgo.com/ip3/' + encodeURIComponent(domain) + '.ico">'
      : '';
    return '<span class="pay-method-icon pay-bank-mono" style="background:' + palette[h % palette.length] + '" aria-hidden="true">' +
      '<span class="pay-bank-mono-letter">' + escapeHtml(letter) + '</span>' + logo + '</span>';
  }

  // After bank rows render, reveal each favicon only once it loads cleanly
  // (CSP-safe: no inline onerror). On error the colored monogram remains.
  function wireBankLogos(root) {
    (root || document).querySelectorAll('img.pay-bank-logo').forEach(function (img) {
      if (img.complete && img.naturalWidth > 0) { img.classList.add('is-loaded'); return; }
      img.addEventListener('load', function () { if (img.naturalWidth > 0) img.classList.add('is-loaded'); });
      img.addEventListener('error', function () { img.classList.remove('is-loaded'); });
    });
  }

  // Non-selectable bank-account rows (chevron instead of radio). When there
  // are no accounts we show ONE muted placeholder row — never a fake account.
  function renderBankAccounts() {
    const list = qs('#payBankAccounts');
    if (!list) return;
    list.innerHTML = '';
    var bankMore = qs('#payBankViewMore');
    if (bankMore) bankMore.innerHTML = '';

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
      row.className = 'pay-method pay-method-bank' + (idx > 0 ? ' pay-method--hidden' : '');
      const acctType = b.accountType || b.type || 'Checking';
      const last4 = b.last4 || b.mask || '';
      const bankName = b.bankName || b.institution || b.name || '';
      const isDefault = (b.isPrimary === true) || (b.isDefault === true);
      // Selectable (radio in the shared payMethod group → mutually
      // exclusive with cards) only when we have a real Vergent bank id to
      // charge. Banks without an id (loan-fallback) stay display-only.
      const bid = parseInt(b.id, 10);
      const selectable = !isNaN(bid) && bid > 0;
      row.innerHTML =
        (selectable
          ? '<input type="radio" name="payMethod" value="bank:' + bid + '">'
          : '') +
        bankMonoHtml(bankName) +
        '<div class="pay-method-body">' +
          '<div class="pay-method-brand">' + escapeHtml(acctType) +
            (last4 ? ' •••• ' + escapeHtml(last4) : '') + '</div>' +
          '<div class="pay-method-meta">' + escapeHtml(bankName) + '</div>' +
        '</div>' +
        (isDefault ? '<span class="pay-method-default">Default</span>' : '') +
        (selectable ? '' : chevron);
      list.appendChild(row);
    });
    wireBankLogos(list);
    if (bankMore && state.bankAccounts.length > 1) {
      bankMore.appendChild(makeViewMore(list, state.bankAccounts.length - 1));
    }
  }

  function applyMethodSelection() {
    const btn = qs('#payChargeBtn');
    const hasSel = !!state.selectedMethodId || !!state.selectedBankId;
    // CVV applies to cards only — hide it when paying by bank (ACH).
    var cvvField = document.querySelector('.pay-field-cvv');
    if (cvvField) cvvField.style.display = state.selectedBankId ? 'none' : '';
    if (btn && !state.submitting) {
      btn.disabled = !hasSel;
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
      var val = String(e.target.value || '');
      if (val.indexOf('bank:') === 0) {
        // Bank (ACH) selected — clear any card selection (and vice versa);
        // the shared radio group already enforces single-select visually.
        state.selectedBankId = val.slice(5);
        state.selectedMethodId = null;
      } else {
        state.selectedMethodId = val;
        state.selectedBankId = null;
      }
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

  // ---------- Add-bank modal ----------
  function openAddBank() {
    clearAddBankError();
    ['#payBankRouting', '#payBankAccount', '#payBankAccountConfirm', '#payBankName'].forEach(function (s) {
      const el = qs(s); if (el) el.value = '';
    });
    const typeSel = qs('#payBankType'); if (typeSel) typeSel.value = 'checking';
    loadBankDir();  // warm the directory so bank-name autofill is instant
    const modal = qs('#payAddBankModal');
    if (!modal) return;
    modal.hidden = false;
    requestAnimationFrame(function () { modal.classList.add('is-open'); });
    const first = qs('#payBankRouting');
    if (first) { try { first.focus(); } catch (e) { /* ignore */ } }
  }
  function closeAddBank() {
    const modal = qs('#payAddBankModal');
    if (!modal) return;
    modal.classList.remove('is-open');
    setTimeout(function () { modal.hidden = true; }, 180);
  }
  function showAddBankError(msg) {
    const el = qs('#payAddBankError');
    if (!el) return;
    el.textContent = msg || "We couldn't save that bank account. Please try again.";
    el.hidden = false;
  }
  function clearAddBankError() {
    const el = qs('#payAddBankError');
    if (el) { el.hidden = true; el.textContent = ''; }
  }

  // Routing-number → bank-name autofill. The FedACH directory
  // (routing -> bank name) is a static JSON bundled with the frontend;
  // lazy-load it the first time the modal needs it (same approach as
  // apply.cashinflash.com, just resolved client-side here).
  var _bankDir = null, _bankDirPromise = null;
  function loadBankDir() {
    if (_bankDir) return Promise.resolve(_bankDir);
    if (_bankDirPromise) return _bankDirPromise;
    _bankDirPromise = fetch('/bank_routing_numbers.json', { credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (j) { _bankDir = j || {}; return _bankDir; })
      .catch(function () { _bankDir = {}; return _bankDir; });
    return _bankDirPromise;
  }
  function lookupBankName() {
    const routingEl = qs('#payBankRouting');
    const nameEl = qs('#payBankName');
    if (!routingEl || !nameEl) return;
    const rn = (routingEl.value || '').replace(/\D/g, '');
    if (rn.length !== 9) { nameEl.value = ''; return; }
    loadBankDir().then(function (dir) {
      // The routing number may have changed while the directory loaded.
      if ((routingEl.value || '').replace(/\D/g, '') !== rn) return;
      nameEl.value = (dir && dir[rn]) ? dir[rn] : '';
    });
  }

  function readNewBank() {
    return {
      routingNumber: String((qs('#payBankRouting') || {}).value || '').replace(/\D/g, ''),
      accountNumber: String((qs('#payBankAccount') || {}).value || '').replace(/\D/g, ''),
      accountNumberConfirm: String((qs('#payBankAccountConfirm') || {}).value || '').replace(/\D/g, ''),
      accountType:   String((qs('#payBankType') || {}).value || 'checking'),
      bankName:      String((qs('#payBankName') || {}).value || '').trim(),
    };
  }
  function validateNewBank(b) {
    if (!/^\d{9}$/.test(b.routingNumber)) return 'Please enter the 9-digit routing number.';
    if (!b.accountNumber || b.accountNumber.length < 4 || b.accountNumber.length > 17) {
      return 'Please enter a valid account number.';
    }
    if (b.accountNumber !== b.accountNumberConfirm) {
      return 'Account numbers don’t match. Please re-enter them.';
    }
    return null;
  }
  function saveBank(e) {
    if (e) e.preventDefault();
    if (state.submitting) return;
    clearAddBankError();

    const bank = readNewBank();
    const err = validateNewBank(bank);
    if (err) { showAddBankError(err); return; }

    const btn = qs('#payAddBankSave');
    state.submitting = true;
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

    api('/api/my-banks', {
      method: 'POST',
      body: {
        routingNumber: bank.routingNumber,
        accountNumber: bank.accountNumber,
        accountType:   bank.accountType,
        bankName:      bank.bankName,
      },
    })
      .then(function () {
        // Don't keep the account number in the DOM after a successful save.
        ['#payBankRouting', '#payBankAccount', '#payBankAccountConfirm', '#payBankName'].forEach(function (s) {
          const el = qs(s); if (el) el.value = '';
        });
        return loadBankAccounts().then(function () {
          closeAddBank();
          showBankAdded(bank.accountNumber.slice(-4));
        });
      })
      .catch(function (e2) {
        const code = (e2 && e2.body && (e2.body.error || e2.body.code)) || '';
        const msgs = {
          invalid_routing_number: 'That routing number doesn’t look right — please double-check the 9 digits.',
          invalid_account_number: 'Please enter a valid account number.',
          vergent_save_failed:    'We couldn’t save that bank account right now. Please try again in a moment.',
        };
        showAddBankError(msgs[code] || 'We couldn’t save that bank account. Please try again.');
      })
      .then(function () {
        state.submitting = false;
        if (btn) { btn.disabled = false; btn.textContent = 'Save bank account'; }
      });
  }
  function showBankAdded(last4) {
    const el = qs('#payCardAddedNote');
    if (!el) return;
    el.textContent = last4
      ? ('Bank account ending ' + last4 + ' added to your profile.')
      : 'Bank account added to your profile.';
    el.hidden = false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
    // Bank (ACH) path — no CVV, no card. Returns a distinct `kind`.
    if (state.selectedBankId) {
      var bank = (state.bankAccounts || []).find(function (b) {
        return String(b.id) === String(state.selectedBankId);
      }) || {};
      return {
        kind: 'bank', amount: amount,
        bankId: state.selectedBankId,
        accountType: bank.accountType || '',
        last4: bank.last4 || '',
        loanId: state.loan && state.loan.id,
      };
    }
    const cvv = String(qs('#payCvv').value || '').trim();
    var sel = (state.methods || []).find(function (m) {
      return m.methodId === state.selectedMethodId;
    }) || {};
    return {
      kind: 'card', amount: amount, cvv: cvv,
      vergentCardId: sel.vergentCardId,
      last4: sel.last4, brand: sel.brand,
      loanId: state.loan && state.loan.id,
    };
  }
  function validatePayForm(f) {
    if (f.kind === 'bank') {
      if (!f.bankId) return 'Please choose a bank account.';
      if (!f.amount || isNaN(f.amount) || f.amount <= 0) return 'Please enter a valid amount.';
      if (f.amount > 5000) return 'Amount must be $5,000 or less.';
      return null;
    }
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

    // Bank (ACH) gets a confirmation modal first (5-business-day notice +
    // estimated clear date). Card pays immediately, as before.
    if (form.kind === 'bank') { openAchConfirm(form); return; }
    doCharge(form);
  }

  // ---------- ACH pending indicator (loan card) ----------
  function _readAchPending(loan) {
    var pend = null;
    try { pend = JSON.parse(sessionStorage.getItem(ACH_PENDING_KEY) || 'null'); }
    catch (e) { pend = null; }
    if (!pend) return null;
    if (loan && String(pend.loanId) !== String(loan.id)) return null;
    // Expire once the estimated clear date has passed (+1 day grace).
    if (pend.clearsBy) {
      var exp = new Date(pend.clearsBy + 'T23:59:59').getTime() + 86400000;
      if (Date.now() > exp) {
        try { sessionStorage.removeItem(ACH_PENDING_KEY); } catch (e) { /* ignore */ }
        return null;
      }
    }
    return pend;
  }
  function _applyAchPending(card, pill, loan) {
    var pend = _readAchPending(loan);
    var strip = document.querySelector('[data-pay-pending-strip]');
    if (!pend) { if (strip) strip.hidden = true; return; }
    if (pill) {
      pill.textContent = 'Processing';
      pill.classList.remove('dash-pill--past-due');
      pill.classList.add('pay-pill--pending');
    }
    if (card) {
      if (!strip) {
        strip = document.createElement('div');
        strip.setAttribute('data-pay-pending-strip', '');
        strip.className = 'pay-pending-strip';
        card.parentNode.insertBefore(strip, card.nextSibling);
      }
      strip.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>' +
        '<span>Bank payment of ' + money(pend.amount) +
        ' is processing — estimated to clear by <strong>' +
        formatDate(pend.clearsBy + 'T00:00:00') +
        '</strong>. Your balance updates once it clears.</span>';
      strip.hidden = false;
    }
  }

  // ---------- ACH confirm modal ----------
  var _pendingAchForm = null;
  function openAchConfirm(form) {
    _pendingAchForm = form;
    var clears = addBusinessDays(5);
    setText(qs('#payAchAmount'), money(form.amount));
    var bankLabel = (form.accountType || 'bank account')
      + (form.last4 ? ' •• ' + form.last4 : '');
    setText(qs('#payAchBank'), bankLabel);
    setText(qs('#payAchClears'), formatDate(clears + 'T00:00:00'));
    var m = qs('#payAchModal');
    if (!m) { _pendingAchForm = null; doCharge(form); return; }  // fallback
    m.hidden = false;
    requestAnimationFrame(function () { m.classList.add('is-open'); });
  }
  function closeAchConfirm() {
    var m = qs('#payAchModal');
    if (!m) return;
    m.classList.remove('is-open');
    m.hidden = true;
  }

  function doCharge(form) {
    state.initialBalance = state.loan ? Number(state.loan.balance) : null;
    const btn = qs('#payChargeBtn');
    state.submitting = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = form.kind === 'bank' ? 'Submitting payment…' : 'Processing payment…';
    }

    // Build the request body for the selected tender. Card body is
    // unchanged; bank (ACH) is the new branch.
    var isBank = form.kind === 'bank';
    var reqBody = isBank
      ? {
          amount:      form.amount,
          useAch:      true,
          bankId:      form.bankId,
          accountType: form.accountType,
          last4:       form.last4,
          loanId:      form.loanId,
        }
      : {
          amount:      form.amount,
          useCardAuto: true,
          cardId:      form.vergentCardId,
          last4:       form.last4,
          brand:       form.brand,
          cvv:         form.cvv,
          loanId:      form.loanId,
        };

    api('/api/my-payment/charge', { method: 'POST', body: reqBody })
      .then(function (res) {
        // Success gate. Card: success + a real transaction id. Bank (ACH):
        // success is enough — ACH is submit-now/settle-later and Vergent
        // may not return a transaction id synchronously.
        var ok = isBank ? (res && res.success === true)
                        : (res && res.success === true && res.transactionId);
        if (ok) {
          const paid = Number(res.authAmount || form.amount);
          const receipt = {
            amount:        paid,
            last4:         res.last4 || form.last4 || '',
            brand:         res.brand || form.brand || (isBank ? 'Bank' : ''),
            transactionId: res.transactionId || res.ledgerId || '',
            when:          Date.now(),
            pending:       isBank,
            clearsBy:      isBank ? (res.estimatedClearDate || addBusinessDays(5)) : null,
          };
          if (isBank) {
            // ACH is pending (~5 business days) — do NOT write the instant
            // card-success banner or imply the balance dropped. Record a
            // pending marker the loan cards read instead.
            try {
              sessionStorage.setItem(ACH_PENDING_KEY, JSON.stringify({
                amount: paid, clearsBy: receipt.clearsBy,
                loanId: form.loanId, when: receipt.when,
              }));
            } catch (e2) { /* non-fatal */ }
          } else {
            sessionStorage.setItem(SUCCESS_KEY, JSON.stringify(receipt));
          }
          return loadLoan()
            .catch(function () {})
            .then(function () { showReceipt(receipt); });
        }
        // Decline — surface the exact reason on the decline page.
        showDecline({
          reason: (res && res.resultText)
                || (isBank ? 'Bank payment was not accepted.' : 'Card declined.'),
          amount: form.amount,
          last4:  form.last4 || (res && res.last4) || '',
          brand:  form.brand || (res && res.brand) || (isBank ? 'Bank' : 'Card'),
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
          missing_loan_or_bank:     'Please pick a bank account.',
          invalid_ach_params:       'Please pick a bank account.',
          bank_not_owned:           'That bank account isn’t on your account. Please pick one of your saved accounts.',
          loan_not_owned:           'We couldn’t match that to your loan. Please refresh and try again.',
        };
        if (inlineMsgs[code]) { showError(inlineMsgs[code]); return; }
        showDecline({
          reason: errBody.resultText
                || 'We couldn\'t reach the payment processor. Please try again.',
          amount: form.amount,
          last4:  form.last4 || '',
          brand:  form.brand || (isBank ? 'Bank' : 'Card'),
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
    const pending  = !!(receipt && receipt.pending);
    const clearsBy = receipt && receipt.clearsBy;

    qs('#payFormCard').hidden = true;

    // Pending (ACH) vs received (card): swap the headline, subline, icon and
    // the tender label so we never imply an ACH payment already posted.
    var rcpt = qs('#payReceipt');
    var h2 = rcpt && rcpt.querySelector('h2');
    var subline = rcpt && rcpt.querySelector('.pay-receipt-subline');
    var icon = rcpt && rcpt.querySelector('.pay-receipt-icon');
    var firstDt = rcpt && rcpt.querySelector('.pay-receipt-grid dt');
    var note = rcpt && rcpt.querySelector('[data-receipt-note]');
    if (rcpt) rcpt.classList.toggle('is-pending', pending);
    if (pending) {
      if (h2) h2.textContent = 'Payment submitted';
      if (subline) subline.textContent = clearsBy
        ? ('Pending — estimated to clear by ' + formatDate(clearsBy + 'T00:00:00'))
        : 'Pending — clears in about 5 business days';
      if (icon) icon.innerHTML = '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>';
      if (firstDt) firstDt.textContent = 'Bank account';
      if (note) {
        note.textContent = 'Bank (ACH) payments take about 5 business days to clear. '
          + 'Your loan balance updates once it clears. If the payment is returned '
          + '(for example, insufficient funds) we’ll let you know.';
        note.hidden = false;
      }
    } else {
      if (h2) h2.textContent = 'Payment received';
      if (subline) subline.textContent = 'applied to your loan';
      if (icon) icon.innerHTML = '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>';
      if (firstDt) firstDt.textContent = 'Card';
      if (note) { note.hidden = true; note.textContent = ''; }
    }

    setText(qs('[data-receipt-amount]'),
      amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','));

    let cardLine = '—';
    if (brand && last4) cardLine = brand + ' ending ' + last4;
    else if (last4)     cardLine = (pending ? 'Bank ending ' : 'Card ending ') + last4;
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
    // Bank rows live in a separate container but share the payMethod radio
    // group, so the change listener must cover them too (ACH selection).
    const banksList = qs('#payBankAccounts');
    if (banksList) banksList.addEventListener('change', onMethodChange);

    // Add-card modal wiring.
    const addBtn = qs('#payAddCardBtn');
    if (addBtn) addBtn.addEventListener('click', openAddCard);
    const addForm = qs('#payAddCardForm');
    if (addForm) addForm.addEventListener('submit', saveCard);
    const addCancel = qs('#payAddCardCancel');
    if (addCancel) addCancel.addEventListener('click', closeAddCard);
    const addBackdrop = qs('#payAddCardBackdrop');
    if (addBackdrop) addBackdrop.addEventListener('click', closeAddCard);

    // ACH confirm modal wiring.
    const achConfirm = qs('#payAchConfirm');
    if (achConfirm) achConfirm.addEventListener('click', function () {
      closeAchConfirm();
      if (_pendingAchForm) { var f = _pendingAchForm; _pendingAchForm = null; doCharge(f); }
    });
    const achCancel = qs('#payAchCancel');
    if (achCancel) achCancel.addEventListener('click', function () {
      _pendingAchForm = null; closeAchConfirm();
    });
    const achBackdrop = qs('#payAchBackdrop');
    if (achBackdrop) achBackdrop.addEventListener('click', function () {
      _pendingAchForm = null; closeAchConfirm();
    });

    // Add-bank modal wiring.
    const addBankBtn = qs('#payAddBankBtn');
    if (addBankBtn) addBankBtn.addEventListener('click', openAddBank);
    const addBankForm = qs('#payAddBankForm');
    if (addBankForm) addBankForm.addEventListener('submit', saveBank);
    const addBankCancel = qs('#payAddBankCancel');
    if (addBankCancel) addBankCancel.addEventListener('click', closeAddBank);
    const addBankBackdrop = qs('#payAddBankBackdrop');
    if (addBankBackdrop) addBankBackdrop.addEventListener('click', closeAddBank);
    const bankRouting = qs('#payBankRouting');
    if (bankRouting) bankRouting.addEventListener('input', function () { this.value = (this.value || '').replace(/\D/g, '').slice(0, 9); lookupBankName(); });
    const bankAccount = qs('#payBankAccount');
    if (bankAccount) bankAccount.addEventListener('input', function () { this.value = (this.value || '').replace(/\D/g, '').slice(0, 17); });
    const bankAccountConfirm = qs('#payBankAccountConfirm');
    if (bankAccountConfirm) bankAccountConfirm.addEventListener('input', function () { this.value = (this.value || '').replace(/\D/g, '').slice(0, 17); });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        const cardModal = qs('#payAddCardModal');
        if (cardModal && !cardModal.hidden) closeAddCard();
        const bankModal = qs('#payAddBankModal');
        if (bankModal && !bankModal.hidden) closeAddBank();
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
      // Keep the payment-method manager visible even with no active loan (so
      // customers can add/update a card before their next loan). The .pay-noloan
      // body class hides the pay-action parts (amount/CVV/breakdown/Pay button).
      if (formCard) formCard.hidden = false;
      document.body.classList.toggle('pay-noloan', !loan);
      if (!loan) {
        var mh = document.querySelector('.pay-method-card .home-card-title');
        var ms = document.querySelector('.pay-method-card .home-card-sub');
        if (mh) mh.textContent = 'Your payment methods';
        if (ms) ms.textContent = "Add or update a debit card so you're ready for your next loan.";
      }
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      showError('Could not load your loan details. Please refresh the page.');
    });
  });
})();
