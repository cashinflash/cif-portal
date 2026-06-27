/* ═══════════════════════════════════════
   CASH IN FLASH — Fast Re-Apply (native in-portal re-loan).

   Three-screen wizard on /request-loan.html:
     1. Confirm details  — prefilled, address/employer/contact editable
     2. Your bank        — reuse a linked bank, or connect one via Plaid
     3. Amount           — request $100–$255 (the engine decides the tier)
   …then a success screen.

   Backend (handlers/loans.py):
     GET  /api/my-reapply/prefill  — editable identity + linked banks
     POST /api/my-reapply/submit   — hand cif-apply the re-loan (RL)
   Plaid Link reuses the existing /api/plaid/{link-token,exchange,connections}.

   The customer's identity + bank are resolved SERVER-SIDE from the JWT;
   the client only chooses the amount, which bank, and edits to its own
   contact/address/employer.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/login.html';

  function $(sel, root) { return (root || document).querySelector(sel); }
  function token() { return sessionStorage.getItem(TOKEN_KEY); }

  var state = {
    min: 100, max: 255, amount: 255,
    banks: [], selectedItemId: null, submitting: false,
    originalPhone: '', phoneVerified: true,
    cards: [], selectedCardId: null,
    onFileAcctLast4: '', bankMatch: null,
  };

  function last4(s) { return String(s == null ? '' : s).replace(/\D/g, '').slice(-4); }

  // ---------- API ----------
  function api(path, options) {
    var t = token();
    if (!t) { window.location.replace(LOGIN_URL); return Promise.reject(new Error('unauthorized')); }
    options = options || {};
    var headers = options.headers || {};
    headers.Authorization = 'Bearer ' + t;
    headers.Accept = 'application/json';
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    return fetch(path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body || undefined,
      credentials: 'omit',
    }).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
        throw new Error('unauthorized');
      }
      return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; })
        .catch(function () { return { ok: r.ok, status: r.status, data: null }; });
    });
  }

  // ---------- Plaid SDK ----------
  function loadPlaidSdk() {
    return new Promise(function (resolve, reject) {
      if (window.Plaid && window.Plaid.create) return resolve(window.Plaid);
      var deadline = Date.now() + 6000;
      var iv = setInterval(function () {
        if (window.Plaid && window.Plaid.create) { clearInterval(iv); resolve(window.Plaid); }
        else if (Date.now() > deadline) { clearInterval(iv); reject(new Error('plaid_sdk_load_failed')); }
      }, 50);
    });
  }
  function fetchLinkToken() {
    return api('/api/plaid/link-token', { method: 'POST', body: '{}' }).then(function (res) {
      if (!res.ok || !res.data || !res.data.linkToken) throw new Error('link_token_failed');
      return res.data.linkToken;
    });
  }
  function exchange(publicToken, metadata) {
    return api('/api/plaid/exchange', {
      method: 'POST', body: JSON.stringify({ publicToken: publicToken, metadata: metadata }),
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  // ---------- Steps ----------
  function showStep(n) {
    Array.prototype.forEach.call(document.querySelectorAll('.rl-step'), function (el) {
      el.hidden = (parseInt(el.getAttribute('data-step'), 10) !== n);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.rl-dot'), function (el) {
      var s = parseInt(el.getAttribute('data-dot'), 10);
      el.classList.toggle('is-active', s === n);
      el.classList.toggle('is-done', s < n);
    });
    try { window.scrollTo(0, 0); } catch (e) {}
  }

  // ---------- Step 1: prefill ----------
  function setVal(id, v) { var el = $('#' + id); if (el) el.value = v == null ? '' : v; }

  function loadPrefill() {
    return api('/api/my-reapply/prefill').then(function (res) {
      if (!res.ok || !res.data || !res.data.ok) throw new Error('prefill_failed');
      var d = res.data;
      var p = d.prefill || {};
      state.min = d.minAmount || 100;
      state.max = d.maxAmount || 255;
      state.amount = state.max;
      state.banks = d.banks || [];
      var nm = ((p.firstName || '') + ' ' + (p.lastName || '')).trim();
      var nameEl = $('#rlName'); if (nameEl) nameEl.textContent = nm || 'Your account';
      var emEl = $('#rlEmail'); if (emEl) emEl.textContent = p.email || '';
      var ini = (((p.firstName || ' ')[0] || '') + ((p.lastName || ' ')[0] || '')).toUpperCase().trim();
      var avEl = $('#rlAvatar'); if (avEl) avEl.textContent = ini || '•';
      setVal('rlAddress', p.address); setVal('rlAddress2', p.address2);
      setVal('rlCity', p.city); setVal('rlState', p.state); setVal('rlZip', p.zip);
      setVal('rlEmployer', p.employer); setVal('rlPhone', p.phone);
      state.originalPhone = String(p.phone || '').replace(/[^0-9]/g, '').slice(-10);
      state.phoneVerified = true;  // unchanged on load → no verification needed
      updatePhoneVerifyUI();
      setupAmount();
      renderBanks();
      renderBankFile(d.bankOnFile);
      loadCards();
      $('#rlLoading').hidden = true;
      $('#rlWizard').hidden = false;
      showStep(1);
      showLegal();
    }).catch(function (e) {
      $('#rlLoading').hidden = true;
      hideHero();
      showLegal();
      $('#rlError').hidden = false;
      if (e && e.message === 'unauthorized') return;
    });
  }

  // Title-case address text ("123 main st" -> "123 Main St").
  function titleCaseAddr(v) {
    return String(v || '').toLowerCase().replace(/\b([a-z])/g, function (m, c) {
      return c.toUpperCase();
    });
  }
  function val(id) { var e = $('#' + id); return e ? (e.value || '') : ''; }

  function gatherEdits() {
    return {
      address: titleCaseAddr(val('rlAddress')).trim(),
      address2: titleCaseAddr(val('rlAddress2')).trim(),
      city: titleCaseAddr(val('rlCity')).trim(),
      state: val('rlState').toUpperCase().trim().slice(0, 2),
      zip: val('rlZip').trim(),
      employer: val('rlEmployer').trim(),
      phone: val('rlPhone').replace(/[^0-9]/g, ''),
    };
  }

  function wireAutoCaps() {
    ['rlAddress', 'rlAddress2', 'rlCity'].forEach(function (id) {
      var el = $('#' + id);
      if (el) el.addEventListener('blur', function () {
        if (this.value.trim()) this.value = titleCaseAddr(this.value).trim();
      });
    });
    var st = $('#rlState');
    if (st) st.addEventListener('blur', function () {
      this.value = (this.value || '').toUpperCase().trim().slice(0, 2);
    });
  }

  // ---------- Phone-change verification (Telnyx OTP) ----------
  function phoneDigits() { return val('rlPhone').replace(/[^0-9]/g, '').slice(-10); }
  function phoneChanged() {
    var d = phoneDigits();
    return d.length >= 10 && d !== state.originalPhone;
  }
  function updatePhoneVerifyUI() {
    var box = $('#rlPhoneVerify');
    if (box) box.hidden = !(phoneChanged() && !state.phoneVerified);
  }
  function pvMsg(text, kind) {
    var m = $('#rlPhoneVerifyMsg');
    if (m) { m.textContent = text || ''; m.className = 'rl-pv-msg' + (kind ? ' ' + kind : ''); }
  }
  function wirePhoneVerify() {
    var ph = $('#rlPhone');
    if (ph) ph.addEventListener('input', function () {
      state.phoneVerified = !phoneChanged();
      var otp = $('#rlPhoneOtpRow'); if (otp) otp.hidden = true;
      var send = $('#rlPhoneSendCode'); if (send) send.textContent = 'Send code';
      pvMsg('', '');
      updatePhoneVerifyUI();
    });
    var send = $('#rlPhoneSendCode');
    if (send) send.addEventListener('click', function () {
      send.disabled = true; pvMsg('Sending…', '');
      api('/api/my-profile/phone/start-verify',
        { method: 'POST', body: JSON.stringify({ phone: val('rlPhone').trim() }) })
        .then(function (r) {
          send.disabled = false;
          if (r.ok && r.data && r.data.ok) {
            var otp = $('#rlPhoneOtpRow'); if (otp) otp.hidden = false;
            send.textContent = 'Resend code';
            pvMsg('We texted a code to ' + (r.data.maskedPhone || 'your number') + '.', 'ok');
            var i = $('#rlPhoneOtp'); if (i) i.focus();
          } else {
            pvMsg((r.data && r.data.detail) || 'Couldn’t send the code. Check the number and try again.', 'err');
          }
        }).catch(function () { send.disabled = false; pvMsg('Network error. Please try again.', 'err'); });
    });
    var vbtn = $('#rlPhoneVerifyBtn');
    if (vbtn) vbtn.addEventListener('click', function () {
      var code = val('rlPhoneOtp').replace(/[^0-9]/g, '');
      if (code.length < 4) { pvMsg('Enter the code we texted you.', 'err'); return; }
      vbtn.disabled = true; pvMsg('Verifying…', '');
      api('/api/my-profile/phone/confirm',
        { method: 'POST', body: JSON.stringify({ phone: val('rlPhone').trim(), code: code }) })
        .then(function (r) {
          vbtn.disabled = false;
          if (r.ok && r.data && !r.data.error) {
            state.phoneVerified = true;
            var box = $('#rlPhoneVerify'); if (box) box.hidden = true;
            pvMsg('', '');
          } else {
            pvMsg((r.data && r.data.detail) || 'That code didn’t match. Try again or resend.', 'err');
          }
        }).catch(function () { vbtn.disabled = false; pvMsg('Network error. Please try again.', 'err'); });
    });
  }
  // Prefilled details start LOCKED (read-only) so the customer confirms at a
  // glance; the Edit toggle unlocks them to change what's stale.
  var LOCK_IDS = ['rlAddress', 'rlAddress2', 'rlCity', 'rlState', 'rlZip', 'rlEmployer', 'rlPhone'];
  function setDetailsLocked(locked) {
    var grid = $('#rlDetailsGrid');
    if (grid) grid.classList.toggle('rl-grid-locked', locked);
    LOCK_IDS.forEach(function (id) { var el = $('#' + id); if (el) el.readOnly = locked; });
    var btn = $('#rlEditToggle');
    if (btn) { btn.classList.toggle('is-editing', !locked); btn.setAttribute('aria-pressed', String(!locked)); }
    var lbl = $('#rlEditToggleLabel'); if (lbl) lbl.textContent = locked ? 'Edit' : 'Done';
  }
  function wireEditToggle() {
    var btn = $('#rlEditToggle'), grid = $('#rlDetailsGrid');
    if (!btn || !grid) return;
    btn.addEventListener('click', function () {
      var unlock = grid.classList.contains('rl-grid-locked');
      setDetailsLocked(!unlock);
      if (unlock) { var f = $('#rlAddress'); if (f) { try { f.focus(); } catch (e) {} } }
    });
    setDetailsLocked(true);
  }

  // The big "Ready for another loan?" hero is page chrome for the wizard only —
  // hide it on the terminal screens (submitted / already-applied / error) so
  // those read as clean, focused confirmations.
  function hideHero() { var h = document.querySelector('.rl-head'); if (h) h.hidden = true; }
  // The legal footer is hidden during the loading state (so it never floats in
  // the middle of an otherwise-empty screen); reveal it once real content shows.
  function showLegal() { var l = $('#rlLegal'); if (l) l.hidden = false; }

  function step1Continue() {
    if (phoneChanged() && !state.phoneVerified) {
      updatePhoneVerifyUI();
      pvMsg('Please verify your new phone number to continue.', 'err');
      var box = $('#rlPhoneVerify');
      if (box && box.scrollIntoView) box.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    showStep(2);
  }

  // Gate: a portal re-loan is only for a customer with NO active loan AND
  // NO application already in review.
  function gateThenLoad() {
    Promise.all([
      api('/api/my-loans/active').then(function (r) { return r.data; },
        function () { return null; }),
      api('/api/my-reapply/status').then(function (r) { return r.data; },
        function () { return null; })
    ]).then(function (res) {
      var active = res[0] || {};
      var rl = res[1] || {};
      if (active && (active.loan || active.pendingSignature)) { blockMessage('active'); return; }
      if (rl && rl.state === 'pending') { blockMessage('pending'); return; }
      loadPrefill();
    }).catch(function () { loadPrefill(); /* fail open to the wizard */ });
  }

  function blockMessage(kind) {
    var ld = $('#rlLoading'); if (ld) ld.hidden = true;
    var wz = $('#rlWizard'); if (wz) wz.hidden = true;
    hideHero();
    showLegal();
    var icon, title, msg;
    if (kind === 'active') {
      icon = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>';
      title = 'You already have an active loan';
      msg = 'You can request a new loan once your current one is paid off. Head to your dashboard to manage it.';
    } else {
      icon = '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>';
      title = 'Your application is being reviewed';
      msg = 'We’ve got your application and we’re reviewing it now. We’ll email or text you with a decision. No need to apply again.';
    }
    var slot = $('#rlError');
    if (!slot) return;
    slot.hidden = false;
    slot.className = 'rl-card rl-done';  // reuse the centered, polished layout
    slot.innerHTML =
      '<div class="rl-done-ico" aria-hidden="true"><svg width="34" height="34" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
      icon + '</svg></div>' +
      '<h2>' + title + '</h2><p>' + msg + '</p>' +
      '<a class="rl-btn" href="/dashboard.html" style="text-decoration:none;">Back to dashboard</a>';
  }

  // Vergent bank-on-file (read-only) — helps the customer eyeball-match
  // the account they're connecting via Plaid to what we have on record.
  function renderBankFile(bf) {
    var panel = $('#rlBankFile');
    if (!panel) return;
    if (!bf || !(bf.bankName || bf.routingNumber || bf.accountNumber)) {
      panel.hidden = true;
      return;
    }
    var setT = function (id, v) { var el = $('#' + id); if (el) el.textContent = v || '—'; };
    setT('rlBfName', bf.bankName);
    setT('rlBfRouting', bf.routingNumber);
    setT('rlBfAccount', bf.accountNumber);
    panel.hidden = false;
    state.onFileAcctLast4 = last4(bf.accountNumber);
    updateBankMatch();
  }

  // Compare the selected/connected Plaid account against the account we have
  // on file in Vergent. We never block (a customer may have legitimately
  // switched banks) — we reassure on a match, warn on a mismatch, and tag the
  // application so the operator confirms the exact account before funding.
  function selectedBank() {
    return (state.banks || []).filter(function (b) { return b.itemId === state.selectedItemId; })[0] || null;
  }
  function updateBankMatch() {
    var el = $('#rlBankMatch');
    if (!el) return;
    var onfile = state.onFileAcctLast4;
    var b = selectedBank();
    var conn = b ? last4(b.accountMask) : '';
    if (!onfile || !conn) { el.hidden = true; el.className = 'rl-bankmatch'; state.bankMatch = null; return; }
    var ok = (onfile === conn);
    state.bankMatch = { matches: ok, connectedLast4: conn, onFileLast4: onfile };
    el.hidden = false;
    el.className = 'rl-bankmatch ' + (ok ? 'is-ok' : 'is-warn');
    if (ok) {
      el.innerHTML = '<span class="rl-bankmatch-ico" aria-hidden="true">✓</span> This is the account we have on file (ending ' + escapeHtml(conn) + ').';
    } else {
      el.innerHTML = '<span class="rl-bankmatch-ico" aria-hidden="true">!</span> '
        + '<span><strong>Double-check your bank.</strong> The account you connected ends in ' + escapeHtml(conn)
        + ', but we have one ending in ' + escapeHtml(onfile) + ' on file. If you switched banks, you can continue. '
        + 'Otherwise, connect the account ending in ' + escapeHtml(onfile) + '.</span>';
    }
  }

  // ---------- Bank + card icons (mirrors the payments page) ----------
  // Real bank logo (favicon over a colored monogram) and card-network marks,
  // reusing the .pay-* classes already in dashboard.css.
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
    for (var i = 0; i < rules.length; i++) if (n.indexOf(rules[i][0]) !== -1) return rules[i][1];
    return '';
  }
  function bankIconHtml(name) {
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
  function wireBankLogos(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('img.pay-bank-logo'), function (img) {
      if (img.complete && img.naturalWidth > 0) { img.classList.add('is-loaded'); return; }
      img.addEventListener('load', function () { if (img.naturalWidth > 0) img.classList.add('is-loaded'); });
      img.addEventListener('error', function () { img.classList.remove('is-loaded'); });
    });
  }
  function cardBrandIconHtml(brand) {
    var b = (brand || '').toLowerCase();
    if (b.indexOf('master') !== -1) return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><svg width="28" height="18" viewBox="0 0 32 20"><circle cx="13" cy="10" r="8" fill="#EB001B"/><circle cx="19" cy="10" r="8" fill="#F79E1B" fill-opacity=".9"/></svg></span>';
    if (b.indexOf('visa') !== -1) return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><span style="color:#1A1F71;font-weight:800;font-style:italic;font-size:.66rem;letter-spacing:.3px">VISA</span></span>';
    if (b.indexOf('amex') !== -1 || b.indexOf('american') !== -1) return '<span class="pay-method-icon pay-brand-icon" style="background:#1F72CD;border-color:#1F72CD" aria-hidden="true"><span style="color:#fff;font-weight:800;font-size:.5rem;letter-spacing:.3px">AMEX</span></span>';
    if (b.indexOf('discover') !== -1) return '<span class="pay-method-icon pay-brand-icon" aria-hidden="true"><span style="color:#E8850D;font-weight:800;font-size:.52rem;letter-spacing:.2px">DISC</span></span>';
    return '<span class="pay-method-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg></span>';
  }

  // Debit card(s) on file (from Vergent, via the payments machinery) —
  // selectable; the chosen card is carried into the application so the
  // operator sees it in the dashboard Debit Card tab.
  function renderCards(cards) {
    var panel = $('#rlCardFile'), root = $('#rlCardList');
    if (!panel || !root) return;
    state.cards = cards || [];
    panel.hidden = false;
    if (!state.cards.length) {
      root.innerHTML = '<p class="rl-muted" style="margin:0 0 2px">No debit card on file yet. Add one below.</p>';
      state.selectedCardId = null;
      return;
    }
    if (!state.selectedCardId) state.selectedCardId = String(state.cards[0].id);
    root.innerHTML = state.cards.map(function (c) {
      var exp = (c.expMonth && c.expYear) ? ('Expires ' + c.expMonth + '/' + String(c.expYear).slice(-2)) : '';
      var on = String(c.id) === state.selectedCardId;
      return '<label class="rl-bank' + (on ? ' is-sel' : '') + '" data-card="' + escapeHtml(String(c.id)) + '">' +
        '<input type="radio" name="rlcard" value="' + escapeHtml(String(c.id)) + '"' + (on ? ' checked' : '') + '>' +
        cardBrandIconHtml(c.brand) +
        '<span class="rl-bank-body"><span class="rl-bank-name">' + escapeHtml(c.brand || 'Card') + ' •••• ' + escapeHtml(c.last4 || '') + '</span>' +
        (exp ? '<span class="rl-bank-meta">' + escapeHtml(exp) + '</span>' : '') + '</span></label>';
    }).join('');
    Array.prototype.forEach.call(root.querySelectorAll('input[name="rlcard"]'), function (inp) {
      inp.addEventListener('change', function () {
        state.selectedCardId = this.value;
        Array.prototype.forEach.call(root.querySelectorAll('.rl-bank'), function (el) {
          el.classList.toggle('is-sel', el.getAttribute('data-card') === state.selectedCardId);
        });
      });
    });
  }
  function selectedCard() {
    var id = state.selectedCardId;
    return (state.cards || []).filter(function (c) { return String(c.id) === String(id); })[0] || null;
  }
  function loadCards() {
    api('/api/my-cards').then(function (r) {
      // The endpoint already returns only usable cards — don't re-filter.
      renderCards((r.data && r.data.cards) || []);
    }).catch(function () { /* leave the panel hidden on error */ });
  }

  // ---------- Step 2: banks ----------
  function renderBanks() {
    var root = $('#rlBankList');
    if (!root) return;
    if (!state.banks.length) {
      root.innerHTML = '<p class="rl-muted">No bank connected yet. Connect your bank below. '
        + 'It only takes a moment and keeps your application secure.</p>';
      updateBankContinue();
      return;
    }
    // Default-select the most-recent bank if nothing chosen yet.
    if (!state.selectedItemId) state.selectedItemId = state.banks[0].itemId;
    root.innerHTML = state.banks.map(function (b) {
      var mask = b.accountMask ? ('···· ' + escapeHtml(b.accountMask)) : '';
      var checked = (b.itemId === state.selectedItemId) ? ' checked' : '';
      return '<label class="rl-bank' + (checked ? ' is-sel' : '') + '" data-item="' + escapeHtml(b.itemId) + '">'
        + '<input type="radio" name="rlbank" value="' + escapeHtml(b.itemId) + '"' + checked + '>'
        + bankIconHtml(b.institutionName)
        + '<span class="rl-bank-body"><span class="rl-bank-name">' + escapeHtml(b.institutionName || 'Bank') + '</span>'
        + (mask ? '<span class="rl-bank-meta">' + mask + '</span>' : '') + '</span>'
        + '</label>';
    }).join('');
    Array.prototype.forEach.call(root.querySelectorAll('input[name="rlbank"]'), function (inp) {
      inp.addEventListener('change', function () {
        state.selectedItemId = this.value;
        Array.prototype.forEach.call(root.querySelectorAll('.rl-bank'), function (el) {
          el.classList.toggle('is-sel', el.getAttribute('data-item') === state.selectedItemId);
        });
        updateBankContinue();
        updateBankMatch();
      });
    });
    updateBankContinue();
    updateBankMatch();
    wireBankLogos(root);
  }

  function updateBankContinue() {
    var btn = $('#rlBankContinue');
    if (btn) btn.disabled = !state.selectedItemId;
  }

  function openLink() {
    var btn = $('#rlConnectBank');
    var orig = btn ? btn.textContent : 'Connect your bank';
    if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
    Promise.all([loadPlaidSdk(), fetchLinkToken()]).then(function (parts) {
      var Plaid = parts[0], linkToken = parts[1];
      if (btn) { btn.disabled = false; btn.textContent = orig; }
      var handler = Plaid.create({
        token: linkToken,
        onSuccess: function (publicToken, metadata) {
          if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
          exchange(publicToken, metadata).then(function (res) {
            if (btn) { btn.disabled = false; btn.textContent = orig; }
            if (res.ok && res.data && res.data.ok) {
              state.selectedItemId = null; // let the refreshed list pick the newest
              api('/api/my-reapply/prefill').then(function (pf) {
                if (pf.ok && pf.data && pf.data.banks) {
                  state.banks = pf.data.banks;
                  renderBanks();
                }
              });
            } else {
              window.alert('Connected, but we couldn’t save the link. Please try again, or call (888) 999-9859.');
            }
          });
        },
        onExit: function (err) { if (err) console.warn('[reapply] link exit', err); },
      });
      handler.open();
    }).catch(function (err) {
      if (btn) { btn.disabled = false; btn.textContent = orig; }
      console.warn('[reapply] openLink failed', err);
      window.alert('We couldn’t open the bank-connect window. Please refresh and try again, or call (888) 999-9859.');
    });
  }

  // ---------- Step 3: amount ----------
  function fmtUsd(n) { return '$' + Number(n).toLocaleString('en-US'); }

  function setAmount(v) {
    v = Math.max(state.min, Math.min(state.max, parseInt(v, 10) || state.min));
    state.amount = v;
    var slider = $('#rlSlider'); if (slider && parseInt(slider.value, 10) !== v) slider.value = v;
    var val = $('#rlAmountVal'); if (val) val.textContent = fmtUsd(v);
    Array.prototype.forEach.call(document.querySelectorAll('.rl-chip'), function (c) {
      c.classList.toggle('is-sel', parseInt(c.getAttribute('data-amt'), 10) === v);
    });
  }

  function setupAmount() {
    var slider = $('#rlSlider');
    if (slider) {
      slider.min = state.min; slider.max = state.max; slider.step = 5; slider.value = state.amount;
      slider.addEventListener('input', function () { setAmount(this.value); });
    }
    var lo = $('#rlAmtLo'); if (lo) lo.textContent = fmtUsd(state.min);
    var hi = $('#rlAmtHi'); if (hi) hi.textContent = fmtUsd(state.max);
    Array.prototype.forEach.call(document.querySelectorAll('.rl-chip'), function (c) {
      c.addEventListener('click', function () { setAmount(this.getAttribute('data-amt')); });
    });
    setAmount(state.amount);
  }

  // ---------- Submit ----------
  function submit() {
    if (state.submitting) return;
    if (!state.selectedItemId) { showStep(2); return; }
    state.submitting = true;
    var btn = $('#rlSubmit');
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
    api('/api/my-reapply/submit', {
      method: 'POST',
      body: JSON.stringify({
        amount: state.amount,
        plaidItemId: state.selectedItemId,
        edits: gatherEdits(),
        debitCard: (function () {
          var c = selectedCard();
          return c ? {
            vergentCardId: c.id, brand: c.brand, last4: c.last4,
            expMonth: c.expMonth, expYear: c.expYear, cardholder: c.cardholder,
          } : null;
        })(),
        bankMatch: state.bankMatch,
      }),
    }).then(function (res) {
      state.submitting = false;
      if (res.ok && res.data && res.data.ok) {
        var amtEl = $('#rlDoneAmount');
        if (amtEl) amtEl.textContent = fmtUsd(res.data.amount || state.amount);
        $('#rlWizard').hidden = true;
        hideHero();
        showLegal();
        $('#rlDone').hidden = false;
        try { window.scrollTo(0, 0); } catch (e) {}
        return;
      }
      if (btn) { btn.disabled = false; btn.textContent = 'Submit application'; }
      var msg = (res.data && res.data.detail) || 'We couldn’t submit your application. Please try again.';
      if (res.data && res.data.error === 'needs_bank') { showStep(2); renderBanks(); }
      window.alert(msg + '\n\nIf this keeps happening, call (888) 999-9859.');
    }).catch(function (e) {
      state.submitting = false;
      if (btn) { btn.disabled = false; btn.textContent = 'Submit application'; }
      if (e && e.message === 'unauthorized') return;
      window.alert('Network error. Please try again, or call (888) 999-9859.');
    });
  }

  // ---------- Google Places address autocomplete (current Places API) ----------
  // Drives a custom, on-brand dropdown off our own #rlAddress field (the new
  // PlaceAutocompleteElement brings its own input + shadow DOM that wouldn't
  // match our styling). No key configured (window.CIF_GMAPS_KEY) → the field
  // stays a plain input, so this is a zero-risk enhancement.
  var _gmapsP = null;
  function loadGmaps(key) {
    if (_gmapsP) return _gmapsP;
    _gmapsP = new Promise(function (resolve, reject) {
      if (window.google && window.google.maps && window.google.maps.importLibrary) return resolve();
      // Surface Google auth failures (wrong/missing API enabled, billing off,
      // bad key, or this site not in the key's HTTP-referrer allowlist).
      try {
        window.gm_authFailure = function () {
          console.error('[reapply] Google Maps auth FAILED (gm_authFailure): ' +
            'check that "Places API (New)" AND "Maps JavaScript API" are enabled, ' +
            'billing is on, and this site is in the key’s HTTP-referrer allowlist. ' +
            'Look just above for the specific *MapError.');
        };
      } catch (e) {}
      var s = document.createElement('script');
      s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) + '&v=weekly&libraries=places&loading=async';
      s.async = true;
      s.onerror = function () { reject(new Error('gmaps_load_failed')); };
      s.onload = function () {
        var deadline = Date.now() + 8000;
        var iv = setInterval(function () {
          if (window.google && window.google.maps && window.google.maps.importLibrary) { clearInterval(iv); resolve(); }
          else if (Date.now() > deadline) { clearInterval(iv); reject(new Error('gmaps_init_timeout')); }
        }, 60);
      };
      document.head.appendChild(s);
    });
    return _gmapsP;
  }
  function setupAddressAutocomplete() {
    var key = (window.CIF_GMAPS_KEY || '').trim();
    var input = $('#rlAddress');
    if (!key || !input || !input.parentNode) return; // graceful: plain field
    var box = input.parentNode; // the <label class="rl-field rl-col2">
    box.style.position = 'relative';
    var menu = document.createElement('div');
    menu.className = 'rl-ac-menu';
    menu.hidden = true;
    box.appendChild(menu);

    var Places = null, token = null, items = [], active = -1, t = null;
    function newToken() { try { token = new Places.AutocompleteSessionToken(); } catch (e) { token = null; } }

    loadGmaps(key).then(function () {
      return window.google.maps.importLibrary('places');
    }).then(function (lib) {
      Places = lib;
      if (!Places || !Places.AutocompleteSuggestion) return;
      input.setAttribute('autocomplete', 'off');
      newToken();
      input.addEventListener('input', onInput);
      input.addEventListener('keydown', onKey);
      document.addEventListener('click', function (e) { if (!box.contains(e.target)) closeMenu(); });
    }).catch(function (e) {
      console.error('[reapply] Google Maps failed to load:', (e && e.message) || e,
        '\nCheck the key, that "Maps JavaScript API" is enabled, and the HTTP-referrer restriction allows this site.');
      /* graceful: plain field stays usable */
    });

    function onInput() {
      if (input.readOnly) return;
      var q = input.value.trim();
      if (t) clearTimeout(t);
      if (q.length < 3) { closeMenu(); return; }
      t = setTimeout(function () { fetchSuggest(q); }, 220);
    }
    function fetchSuggest(q) {
      if (!Places || !Places.AutocompleteSuggestion) return;
      if (!token) newToken();
      Places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
        input: q, includedRegionCodes: ['us'],
        includedPrimaryTypes: ['street_address', 'premise', 'subpremise'],
        sessionToken: token,
      }).then(function (res) {
        items = (res && res.suggestions) || [];
        if (!items.length) {
          console.warn('[reapply] address autocomplete: 0 suggestions (request OK). ' +
            'If this is every query, confirm "Places API (New)" is enabled + billing is on.');
        }
        renderMenu();
      }).catch(function (e) {
        console.error('[reapply] address autocomplete request FAILED:', (e && e.message) || e,
          '\nFix: enable "Places API (New)" + "Maps JavaScript API", turn on billing, and add this ' +
          'site to the key’s HTTP-referrer allowlist (must include the CloudFront URL while testing).');
        closeMenu();
      });
    }
    function predText(p, which) {
      var f = p && p[which];
      return (f && f.text) ? f.text : '';
    }
    function renderMenu() {
      if (!items.length) { closeMenu(); return; }
      active = -1;
      menu.innerHTML = items.map(function (s, i) {
        var p = s.placePrediction || {};
        var main = predText(p, 'mainText') || predText(p, 'text');
        var sec = predText(p, 'secondaryText');
        return '<div class="rl-ac-item" data-i="' + i + '"><span class="rl-ac-main">' + escapeHtml(main) + '</span>'
          + (sec ? '<span class="rl-ac-sec">' + escapeHtml(sec) + '</span>' : '') + '</div>';
      }).join('');
      menu.hidden = false;
      Array.prototype.forEach.call(menu.querySelectorAll('.rl-ac-item'), function (el) {
        // mousedown (not click) so it fires before the input's blur closes us.
        el.addEventListener('mousedown', function (ev) { ev.preventDefault(); choose(parseInt(el.getAttribute('data-i'), 10)); });
      });
    }
    function closeMenu() { menu.hidden = true; menu.innerHTML = ''; items = []; active = -1; }
    function hl() {
      Array.prototype.forEach.call(menu.querySelectorAll('.rl-ac-item'), function (el, i) {
        el.classList.toggle('is-active', i === active);
      });
    }
    function onKey(e) {
      if (menu.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(items.length - 1, active + 1); hl(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); hl(); }
      else if (e.key === 'Enter') { if (active >= 0) { e.preventDefault(); choose(active); } }
      else if (e.key === 'Escape') { closeMenu(); }
    }
    function choose(i) {
      var s = items[i];
      if (!s || !s.placePrediction) { closeMenu(); return; }
      var place;
      try { place = s.placePrediction.toPlace(); } catch (e) { closeMenu(); return; }
      place.fetchFields({ fields: ['addressComponents'] }).then(function (r) {
        var comps = (r && r.place && r.place.addressComponents) || place.addressComponents || [];
        applyComponents(comps);
        closeMenu();
        newToken(); // a selection ends the billing session
      }).catch(function () { closeMenu(); });
    }
    function comp(comps, type, useShort) {
      var c = (comps || []).filter(function (x) { return (x.types || []).indexOf(type) >= 0; })[0];
      if (!c) return '';
      return useShort ? (c.shortText || c.longText || '') : (c.longText || c.shortText || '');
    }
    function applyComponents(comps) {
      var street = (comp(comps, 'street_number') + ' ' + comp(comps, 'route')).trim();
      if (street) setVal('rlAddress', street);
      var city = comp(comps, 'locality') || comp(comps, 'sublocality') || comp(comps, 'postal_town');
      if (city) setVal('rlCity', city);
      var st = comp(comps, 'administrative_area_level_1', true);
      if (st) setVal('rlState', st);
      var zip = comp(comps, 'postal_code');
      if (zip) setVal('rlZip', zip);
    }
  }

  // ---------- Wiring ----------
  function init() {
    if (!$('#rlWizard')) return; // not on the re-apply page
    var s1 = $('#rlStep1Continue'); if (s1) s1.addEventListener('click', step1Continue);
    var b1 = $('#rlBankBack'); if (b1) b1.addEventListener('click', function () { showStep(1); });
    var bc = $('#rlBankContinue'); if (bc) bc.addEventListener('click', function () { if (state.selectedItemId) showStep(3); });
    var a1 = $('#rlAmtBack'); if (a1) a1.addEventListener('click', function () { showStep(2); });
    var cb = $('#rlConnectBank'); if (cb) cb.addEventListener('click', openLink);
    var sub = $('#rlSubmit'); if (sub) sub.addEventListener('click', submit);
    wireAutoCaps();
    wirePhoneVerify();
    wireEditToggle();
    setupAddressAutocomplete();
    gateThenLoad();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
