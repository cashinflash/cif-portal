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
  };

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
    }).catch(function (e) {
      $('#rlLoading').hidden = true;
      hideHero();
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
        '<span class="rl-bank-ico" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg></span>' +
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
        + '<span class="rl-bank-ico" aria-hidden="true">'
        + '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 14h6M9 18h6"/></svg>'
        + '</span>'
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
      });
    });
    updateBankContinue();
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
      }),
    }).then(function (res) {
      state.submitting = false;
      if (res.ok && res.data && res.data.ok) {
        var amtEl = $('#rlDoneAmount');
        if (amtEl) amtEl.textContent = fmtUsd(res.data.amount || state.amount);
        $('#rlWizard').hidden = true;
        hideHero();
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
    gateThenLoad();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
