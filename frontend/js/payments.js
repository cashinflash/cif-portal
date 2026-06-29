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
  // Pending-ACH detection, dates, pill, strip, and modal live in the shared
  // cif-ach.js module (window.CifAch) so they stay identical on every page.
  const ACH_PENDING_KEY = (window.CifAch && window.CifAch.KEY) || 'cif_ach_pending';
  function addBusinessDays(n) {
    return window.CifAch ? window.CifAch.addBusinessDays(n) : '';
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
  var PAY_ENDPOINT = '/api/my-payment/loan-summary';

  // Render the pay-page summary card from a loan-summary payload. Extracted so
  // the SWR cache (cif-loancache.js) can paint it INSTANTLY from cache, then
  // again from the fresh fetch. Returns the loan object (or null when none).
  function renderLoanSummary(data) {
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
        // No active loan to pay → drop the card/bank selector radios (the saved
        // methods read as a plain "wallet" list instead).
        document.body.classList.add('cif-pay-no-active');
        return null;
      }
      const loan = data.loan;
      card.classList.remove('loan-card--art', 'loan-card--paidup');
      state.loan = loan;
      // Gate the "Need extra cash?" banner: never offer a new loan while an
      // active loan with a balance is open.
      var hasActiveLoan = !!(loan && Number(loan.balance) > 0);
      // Selector radios only make sense when there's a balance to pay.
      document.body.classList.toggle('cif-pay-no-active', !hasActiveLoan);
      var bannerActive = document.querySelector('.app-loan-banner');
      if (bannerActive) bannerActive.style.display = hasActiveLoan ? 'none' : '';
      setText(qs('[data-pay-loan-id]', card), (loan.publicId || loan.id || '—'));
      var displayDue = (loan.onPaymentPlan && loan.amountDue != null) ? loan.amountDue : loan.balance;
      setText(qs('[data-pay-balance]', card), money(displayDue));
      var _funded = (loan.principal != null ? loan.principal
        : (loan.principalBalance != null ? loan.principalBalance : null));
      setText(qs('[data-pay-funded]', card), _funded != null ? money(_funded) : '—');
      const caption = qs('[data-pay-caption]', card);
      if (caption) {
        // In the redesigned card this value sits under the "Due date" label,
        // so show just the date (the amount is already the big "Amount due").
        caption.textContent = loan.nextDueDate ? formatDate(loan.nextDueDate) : '—';
      }
      // "Due in N days" pill — amber within a week, red past due.
      (function () {
        var els = card.querySelectorAll('[data-loan-countdown]');
        if (!els.length) return;
        var text = '', cls = '';
        if (loan.nextDueDate) {
          var due = new Date(loan.nextDueDate);
          if (!isNaN(due.getTime())) {
            var today = new Date();
            var a = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
            var b = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
            var days = Math.round((a - b) / 86400000);
            if (days < 0) { text = Math.abs(days) + (Math.abs(days) === 1 ? ' day' : ' days') + ' past due'; cls = 'is-late'; }
            else if (days === 0) { text = 'Due today'; cls = 'is-soon'; }
            else if (days === 1) { text = 'Due tomorrow'; cls = 'is-soon'; }
            else { text = 'Due in ' + days + ' days'; if (days <= 7) cls = 'is-soon'; }
          }
        }
        Array.prototype.forEach.call(els, function (el) {
          el.classList.remove('is-soon', 'is-late');
          if (!text) { el.hidden = true; return; }
          if (cls) el.classList.add(cls);
          el.textContent = text; el.hidden = false;
        });
      })();

      const pill = qs('[data-pay-loan-status]', card);
      // Past-due detection IDENTICAL to Home + Loans (statusPillClass): the
      // status string alone doesn't always say "past due" — Vergent flags it via
      // the daysLate field, so we check both (that's why this card used to stay
      // green on a past-due loan).
      var _status = (loan.status || '').toLowerCase();
      var _daysLate = (loan.daysLate || '').toLowerCase();
      var _past = !!loan.isOutstanding && (
        _status.indexOf('past') !== -1 || _status.indexOf('delinquent') !== -1 ||
        (_daysLate && _daysLate !== 'not late'));
      var _dpd = _past ? daysPastDue(loan) : 0;
      var _soft = _past && _dpd >= 1 && _dpd <= 4;
      if (pill) {
        pill.textContent = _past ? 'Past due' : 'Current';
        pill.classList.toggle('dash-pill--past-due', _past);
      }
      // Bank (ACH) payment pending → consistent "Processing" pill + strip
      // (shared module; identical to the home + loans cards).
      if (window.CifAch) {
        var _ach = CifAch.info(loan);
        CifAch.renderStrip(_ach);
        if (_ach) CifAch.applyPill(qs('[data-pay-loan-status]', card), _ach);
      }
      // Recolor the summary card by past-due severity (amber 1–4 days, red 5+),
      // matching Home — independent of the pill so it works even if absent.
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
      // Lock the payment amount to the full amount due (no partial/custom
      // amounts). setLockedAmount() reads state.loan and writes both the hidden
      // #payAmount (used by submit/validate) and the read-only display.
      setLockedAmount();
      // If this customer is awaiting signature (known synchronously from the
      // preflight flag), rebuild the card to the pending layout NOW — same
      // synchronous tick that rendered the default summary — so the old version
      // never paints before the async e-sign gate runs.
      if (document.documentElement.classList.contains('cif-pending-signature') && window.CifEsign) {
        CifEsign.gateCard(card, loan);
      }
      return loan;
  }

  function loadLoan() {
    // Stale-while-revalidate: paint the summary INSTANTLY from cache (so
    // navigating to Payments is instant), then refresh in the background. The
    // cache is cleared on a successful payment, so a post-payment refresh never
    // shows a stale balance.
    var cached = window.CifLoanCache && CifLoanCache.get(PAY_ENDPOINT);
    if (cached) { try { renderLoanSummary(cached); } catch (e) { /* fall through to fetch */ } }
    return api(PAY_ENDPOINT).then(function (data) {
      if (window.CifLoanCache) CifLoanCache.set(PAY_ENDPOINT, data);
      return renderLoanSummary(data);
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
    // Cap saved cards at 3 — silently hide "Add a debit card" once at the max.
    var addCardBtn = qs('#payAddCardBtn');
    if (addCardBtn) addCardBtn.style.display = (state.methods.length >= 3) ? 'none' : '';
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
      const acctType = b.accountType || b.type || 'Checking';
      const last4 = b.last4 || b.mask || '';
      const bankName = b.bankName || b.institution || b.name || '';
      const isDefault = (b.isPrimary === true) || (b.isDefault === true);
      // Selectable (radio in the shared payMethod group → mutually
      // exclusive with cards) only when we have a real Vergent bank id to
      // charge. Banks without an id (loan-fallback) stay display-only.
      const bid = parseInt(b.id, 10);
      const selectable = !isNaN(bid) && bid > 0;
      // Selectable rows are <label> so a tap ANYWHERE on the row toggles its
      // radio (matches the cards list); display-only rows stay a plain <div>.
      const row = document.createElement(selectable ? 'label' : 'div');
      row.className = 'pay-method pay-method-bank' + (idx > 0 ? ' pay-method--hidden' : '');
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
    // Cap saved banks at 3 — silently hide "Add a bank account" once at the max.
    var addBankBtn = qs('#payAddBankBtn');
    if (addBankBtn) addBankBtn.style.display = (state.bankAccounts.length >= 3) ? 'none' : '';
  }

  // Highlight the selected plan option (green border) — inline, no CSS dep.
  function stylePlanOpts() {
    var opts = document.querySelectorAll('[data-plan-opt]');
    Array.prototype.forEach.call(opts, function (lbl) {
      var r = lbl.querySelector('input[type="radio"]');
      var on = !!(r && r.checked);
      lbl.style.borderColor = on ? '#16a34a' : '#e2e8f0';
      lbl.style.background = on ? 'rgba(22,163,74,.05)' : '';
    });
  }

  // Payment amount is never free-entry — no partial/custom amounts.
  //  • Regular loan  → locked to the full balance (the choice row stays hidden;
  //    the breakdown + Pay button carry the figure).
  //  • Payment plan  → a two-way choice: the scheduled installment (amountDue)
  //    or pay off the full balance (payoff). The selected radio drives it.
  // Writes the hidden #payAmount that submit/validate read. Returns the amount.
  function setLockedAmount() {
    var loan = state.loan;
    var inp = qs('#payAmount');
    var row = qs('#payPlanChoiceRow');
    if (!loan) {
      if (inp) inp.value = '';
      if (row) row.hidden = true;
      return null;
    }
    var payoff = (loan.balance != null) ? Number(loan.balance)
      : (loan.payoffAmount != null ? Number(loan.payoffAmount) : null);
    var installment = (loan.amountDue != null) ? Number(loan.amountDue) : null;
    var isPlan = !!loan.onPaymentPlan && installment != null && payoff != null
      && installment + 0.01 < payoff;
    var n;
    if (isPlan) {
      if (row) row.hidden = false;
      var di = qs('[data-plan-installment]'); if (di) di.textContent = money(installment);
      var dp = qs('[data-plan-payoff]');      if (dp) dp.textContent = money(payoff);
      var sel = document.querySelector('input[name="payPlanChoice"]:checked');
      n = (sel && sel.value === 'payoff') ? payoff : installment;
      stylePlanOpts();
    } else {
      if (row) row.hidden = true;
      n = payoff;  // regular loan → full balance, no choice
    }
    if (inp) inp.value = (n != null && !isNaN(n) && n > 0) ? n.toFixed(2) : '';
    return n;
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
      if ((!amt || isNaN(amt) || amt <= 0) && state.loan) {
        amt = (state.loan.onPaymentPlan && state.loan.amountDue != null)
          ? Number(state.loan.amountDue) : Number(state.loan.balance);
      }
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
    if ((state.methods || []).length >= 3) return;  // max 3 cards
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
    modal.hidden = true;
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
    if ((state.bankAccounts || []).length >= 3) return;  // max 3 bank accounts
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
          // Bring the just-added bank account to the #1 spot.
          var nl4 = (bank.accountNumber || '').slice(-4);
          var arr = state.bankAccounts || [];
          var mi = -1;
          for (var i = 0; i < arr.length; i++) {
            if (arr[i] && String(arr[i].last4) === String(nl4)) { mi = i; break; }
          }
          if (mi > 0) { arr.unshift(arr.splice(mi, 1)[0]); }
          renderBankAccounts();
          closeAddBank();
          showBankAdded(nl4);
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
    const digits = String(value || '').replace(/\D/g, '').slice(0, 16);
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

    // Bank (ACH) → its own confirm modal (CVV not applicable).
    if (form.kind === 'bank') {
      const berr = validatePayForm(form);
      if (berr) { showError(berr); return; }
      openAchConfirm(form);
      return;
    }
    // Card → validate everything EXCEPT the CVV (the CVV is entered in the
    // confirmation modal), then open the confirm modal so a single tap never
    // silently charges the card.
    if (!form.vergentCardId) { showError('Please choose a saved card, or add one below.'); return; }
    if (!form.amount || isNaN(form.amount) || form.amount <= 0) { showError('Please enter a valid amount.'); return; }
    if (form.amount > 5000) { showError('Amount must be $5,000 or less.'); return; }
    openCardConfirm(form);
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

  // ---------- Card confirm modal (also collects the CVV at authorize time) ----------
  var _pendingCardForm = null;
  function openCardConfirm(form) {
    _pendingCardForm = form;
    setText(qs('#payCardConfirmAmount'), money(form.amount));
    var cardLabel = (form.brand || 'Card') + (form.last4 ? ' •• ' + form.last4 : '');
    setText(qs('#payCardConfirmCard'), cardLabel);
    setText(qs('#payCardConfirmPay'), 'Confirm & Pay ' + money(form.amount));
    var cv = qs('#payCvv'); if (cv) cv.value = '';
    var er = qs('#payCardConfirmError'); if (er) { er.hidden = true; er.textContent = ''; }
    var m = qs('#payCardConfirmModal');
    if (!m) {  // modal missing — prompt for CVV so we never charge blind
      var c = window.prompt('Enter your card security code (CVV) to confirm payment of ' + money(form.amount));
      if (!c || !/^\d{3,4}$/.test(String(c).trim())) { showError('Please enter the 3- or 4-digit CVV.'); _pendingCardForm = null; return; }
      form.cvv = String(c).trim(); _pendingCardForm = null; doCharge(form); return;
    }
    m.hidden = false;
    requestAnimationFrame(function () { m.classList.add('is-open'); });
    setTimeout(function () { var i = qs('#payCvv'); if (i) i.focus(); }, 120);
  }
  function closeCardConfirm() {
    _pendingCardForm = null;
    var m = qs('#payCardConfirmModal');
    if (!m) return;
    m.classList.remove('is-open');
    m.hidden = true;
  }
  function confirmCardPay() {
    var form = _pendingCardForm;
    if (!form) return;
    var cvv = String((qs('#payCvv') || {}).value || '').trim();
    if (!/^\d{3,4}$/.test(cvv)) {
      var er = qs('#payCardConfirmError');
      if (er) { er.textContent = 'Please enter the 3- or 4-digit security code.'; er.hidden = false; }
      var i = qs('#payCvv'); if (i) i.focus();
      return;
    }
    form.cvv = cvv;
    _pendingCardForm = null;
    var m = qs('#payCardConfirmModal');
    if (m) { m.classList.remove('is-open'); m.hidden = true; }
    doCharge(form);
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
          // The balance just changed — drop the SWR cache so the post-payment
          // reload here AND the next page (Home/Loans) fetch fresh, never a
          // stale pre-payment balance. loadLoan() re-populates it immediately.
          if (window.CifLoanCache) CifLoanCache.clear();
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
          // Bring the just-added card to the #1 spot (and select it).
          if (match) {
            state.methods = [match].concat(
              (state.methods || []).filter(function (m) { return m !== match; }));
          }
          state.selectedMethodId = match ? match.methodId
            : (state.methods && state.methods.length ? state.methods[0].methodId : null);
          state.selectedBankId = null;
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
          + 'Your loan balance updates once it clears.';
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
    var isBank = !!info.isBank || info.brand === 'Bank';
    var reason = String(info.reason || (isBank ? 'Bank payment was not accepted.' : 'Card declined.')).trim();
    var html = reason.split(/\s*;\s+/)
      .map(function (line) { return escapeHtml(line); })
      .join('<br>');
    var reasonEl = qs('#payDeclineReason');
    if (reasonEl) reasonEl.innerHTML = html;

    // Bank (ACH) wording vs card wording — a bank payment must never say
    // "card declined / card issuer / try a different card".
    var sub = qs('[data-decline-sub]');
    if (sub) {
      sub.innerHTML = isBank
        ? 'We couldn’t submit your bank payment, so it was <strong style="color:#c0392b">not scheduled</strong>. Nothing has been applied to your loan.'
        : 'Your card was <strong style="color:#c0392b">declined</strong>. Nothing has been applied to your loan.';
    }
    setText(qs('[data-decline-reason-label]'), isBank ? 'What happened' : 'Reason from your card issuer');
    setText(qs('[data-decline-card-label]'), isBank ? 'Bank account' : 'Card');
    setText(qs('[data-decline-advice]'), isBank
      ? 'Please try again in a moment, or pay with a debit card instead. If it keeps happening, give us a call and we’ll help.'
      : "Try a different debit card, or call the number on the back of your card to confirm it's active and has available funds. Then come back and try again.");
    var tryBtn = qs('#payTryAgainBtn');
    if (tryBtn) tryBtn.textContent = isBank ? 'Try again' : 'Try a different card';

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
    setLockedAmount();  // re-lock to the full amount due (no manual entry)
    const cvv = qs('#payCvv');    if (cvv) cvv.value = '';
    const err = qs('#payError'); if (err) { err.hidden = true; err.textContent = ''; }
    const note = qs('#payCardAddedNote'); if (note) { note.hidden = true; note.textContent = ''; }
    // If a bank (ACH) payment is now pending, don't reopen the form — block a
    // second payment and show the "in progress" panel instead.
    if (state.esign) {
      var _ec = qs('#payFormCard'); if (_ec) _ec.hidden = true;
      CifEsign.block(state.esign);
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    if (applyAchGate(state.loan)) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    qs('#payFormCard').hidden = false;
    loadMethods();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // Show the "payment in progress" panel instead of the pay form while an ACH
  // is pending (returns true if blocked). Single chokepoint used by init +
  // "make another payment".
  function applyAchGate(loan) {
    var ach = window.CifAch ? CifAch.info(loan) : null;
    var formCard = qs('#payFormCard');
    var blocked = qs('#payAchBlocked');
    // Only BLOCK while a payment is still pending. A returned ACH must let the
    // customer pay again (the strip explains what happened).
    if (ach && ach.state !== 'pending') ach = null;
    if (ach) {
      if (formCard) formCard.hidden = true;
      if (blocked) {
        var dEl = blocked.querySelector('[data-ach-blocked-date]');
        if (dEl) dEl.textContent = ach.clearsBy
          ? ('by ' + CifAch.fmtDate(ach.clearsBy)) : 'in about 5 business days';
        blocked.hidden = false;
      }
      return true;
    }
    if (blocked) blocked.hidden = true;
    return false;
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
    const addClose = qs('#payAddCardClose');
    if (addClose) addClose.addEventListener('click', closeAddCard);
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

    // Card confirm modal wiring (Confirm & Pay / Cancel / backdrop).
    const cardConfirmPay = qs('#payCardConfirmPay');
    if (cardConfirmPay) cardConfirmPay.addEventListener('click', confirmCardPay);
    const cardConfirmCancel = qs('#payCardConfirmCancel');
    if (cardConfirmCancel) cardConfirmCancel.addEventListener('click', closeCardConfirm);
    const cardConfirmBackdrop = qs('#payCardConfirmBackdrop');
    if (cardConfirmBackdrop) cardConfirmBackdrop.addEventListener('click', closeCardConfirm);
    const cardConfirmCvv = qs('#payCvv');
    if (cardConfirmCvv) cardConfirmCvv.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); confirmCardPay(); }
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
    // Payment-plan amount choice (installment vs full payoff) → re-lock the
    // hidden amount + refresh the Pay-now button label. The amount is no longer
    // user-editable, so the old free-text blur handler is gone.
    document.addEventListener('change', function (e) {
      if (e.target && e.target.name === 'payPlanChoice') {
        setLockedAmount();
        applyMethodSelection();
      }
    });

    // Load loan + methods in parallel.
    const loanP = loadLoan();
    const methodsP = loadMethods();
    loadBankAccounts();
    const esignP = window.CifEsign ? CifEsign.fetchPending() : Promise.resolve([]);
    Promise.all([loanP, methodsP, esignP]).then(function (results) {
      const loan = results[0];
      const formCard = qs('#payFormCard');
      // Awaiting e-signature → there's nothing to pay until the loan is signed
      // and funded. Block the form and show the Review & sign prompt instead.
      state.esign = (loan && window.CifEsign) ? CifEsign.infoForLoan(loan, results[2] || []) : null;
      if (state.esign) {
        CifEsign.gateCard(qs('#paySummary'), loan);
        if (formCard) formCard.hidden = true;
        var _ab = qs('#payAchBlocked'); if (_ab) _ab.hidden = true;
        CifEsign.block(state.esign);
        document.body.classList.remove('pay-noloan');
        return;
      }
      // Bank (ACH) payment pending → block a SECOND payment (card or bank)
      // until it clears. Robust chokepoint: applies no matter how the customer
      // reached this page (home CTA, tab bar, or direct URL).
      if (applyAchGate(loan)) {
        document.body.classList.remove('pay-noloan');
        return;
      }
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
