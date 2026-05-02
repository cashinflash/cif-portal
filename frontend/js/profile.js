/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL · PROFILE
   Banking-style profile page. Each row opens a modal sheet for
   intentional, reviewed edits. Phone is two-step (Telnyx Verify).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var API_BASE = '/api';
  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/start.html';
  var PROFILE_ENDPOINT = API_BASE + '/my-profile';
  var EMAIL_ENDPOINT = API_BASE + '/my-profile/email';
  var ADDRESS_ENDPOINT = API_BASE + '/my-profile/address';
  var PHONE_START_ENDPOINT = API_BASE + '/my-profile/phone/start-verify';
  var PHONE_CONFIRM_ENDPOINT = API_BASE + '/my-profile/phone/confirm';

  var STATES = ['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC'];

  // ---------- Helpers ----------
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function setText(el, v) { if (el) el.textContent = v; }
  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function fmtPhone(raw) {
    var d = String(raw || '').replace(/\D/g, '');
    if (d.length === 11 && d[0] === '1') d = d.slice(1);
    if (d.length === 10) {
      return '(' + d.slice(0, 3) + ') ' + d.slice(3, 6) + '-' + d.slice(6);
    }
    return raw || '—';
  }
  function decodeJwt(t) {
    try {
      var p = t.split('.')[1];
      var b = p.replace(/-/g, '+').replace(/_/g, '/');
      var pad = b + '==='.slice((b.length + 3) % 4);
      return JSON.parse(decodeURIComponent(
        atob(pad).split('').map(function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      ));
    } catch (e) { return null; }
  }
  function isExpired(c) {
    if (!c || !c.exp) return true;
    return c.exp * 1000 < Date.now() + 15 * 1000;
  }

  function apiFetch(path, options) {
    options = options || {};
    options.credentials = 'omit';
    options.headers = Object.assign({
      'Authorization': 'Bearer ' + token,
      'Accept': 'application/json',
    }, options.headers || {});
    if (options.body && typeof options.body !== 'string') {
      options.body = JSON.stringify(options.body);
      options.headers['Content-Type'] = 'application/json';
    }
    return fetch(path, options).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
        throw new Error('unauthorized');
      }
      return res.json().then(function (data) {
        return { status: res.status, data: data };
      }, function () {
        return { status: res.status, data: {} };
      });
    });
  }

  // ---------- Auth guard ----------
  var token = sessionStorage.getItem(TOKEN_KEY);
  var claims = token ? decodeJwt(token) : null;
  if (!token || !claims || isExpired(claims)) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_URL + '?reason=session_expired');
    return;
  }

  var _profile = null;
  var _pendingPhone = null;        // 10-digit phone awaiting code confirmation
  var _modalCurrent = null;        // which edit type is open ('email' | 'phone' | 'address')
  var _lastFocused = null;         // restore focus on modal close

  // ---------- Init ----------
  document.addEventListener('DOMContentLoaded', function () {
    var first = (claims.given_name || '').trim();
    setText(qs('#userChip'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    setText(qs('#sidebarUserName'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    var year = qs('#footerYear');
    if (year) year.textContent = String(new Date().getFullYear());

    wireRows();
    wireModal();
    loadProfile();
  });

  function wireRows() {
    qsa('.profile-row[data-edit]').forEach(function (row) {
      var which = row.getAttribute('data-edit');
      row.addEventListener('click', function () { openModal(which); });
      row.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openModal(which); }
      });
    });
  }

  function wireModal() {
    var modal = qs('#profileModal');
    if (!modal) return;
    qsa('[data-modal-action="close"]', modal).forEach(function (el) {
      el.addEventListener('click', closeModal);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && _modalCurrent) closeModal();
    });
  }

  function loadProfile() {
    apiFetch(PROFILE_ENDPOINT).then(function (r) {
      _profile = r.data || {};
      renderProfile(_profile);
    }).catch(function (err) {
      if (err && err.message === 'unauthorized') return;
      banner('error', "We couldn't load your profile. Please refresh.");
    });
  }

  function renderProfile(p) {
    // Identity card
    var first = (p.firstName || claims.given_name || '').trim();
    var last  = (p.lastName  || claims.family_name || '').trim();
    var fullName = (first + ' ' + last).trim() || (p.vergentEmail || claims.email || 'Welcome');
    setText(qs('#profileFullName'), fullName);

    var initials = ((first[0] || '') + (last[0] || '')).toUpperCase();
    if (!initials) {
      var em = (p.vergentEmail || claims.email || '');
      initials = em ? em[0].toUpperCase() : '—';
    }
    setText(qs('#profileInitials'), initials);

    if (p.statusName) {
      var pill = qs('#profileStatusPill');
      var txt = qs('#profileStatusText');
      var ok = String(p.statusName).toLowerCase() === 'good';
      txt.textContent = ok ? 'Account in good standing' : ('Account: ' + p.statusName);
      pill.hidden = false;
      pill.classList.toggle('profile-identity-status--bad', !ok);
    }

    // Email
    var email = p.vergentEmail || p.email || '—';
    setText(qs('#profileEmailValue'), email);

    // Phone
    var phone = p.vergentPhone || p.phone || '';
    setText(qs('#profilePhoneValue'), phone ? fmtPhone(phone) : '—');

    // Address
    var addr = p.vergentAddress || null;
    var addrEl = qs('#profileAddressValue');
    if (addr && addr.addr1) {
      var cityState = [addr.city, addr.state].filter(Boolean).join(', ');
      var line2 = (cityState + (addr.zip ? ' ' + addr.zip : '')).trim();
      addrEl.innerHTML = escape(addr.addr1) +
        (addr.addr2 ? ', ' + escape(addr.addr2) : '') +
        '<br>' + escape(line2);
    } else {
      addrEl.textContent = '—';
    }
  }

  // ---------- Modal flow ----------
  function openModal(which) {
    _modalCurrent = which;
    _lastFocused = document.activeElement;
    var modal = qs('#profileModal');
    var title = qs('#profileModalTitle');
    var body  = qs('#profileModalBody');

    if (which === 'email') {
      title.textContent = 'Update email address';
      body.innerHTML = renderEmailForm();
      bindEmailForm();
    } else if (which === 'phone') {
      title.textContent = 'Update mobile phone';
      body.innerHTML = renderPhoneStartForm();
      bindPhoneStartForm();
    } else if (which === 'address') {
      title.textContent = 'Update home address';
      body.innerHTML = renderAddressForm();
      bindAddressForm();
    } else {
      return;
    }

    document.body.style.overflow = 'hidden';
    modal.hidden = false;
    requestAnimationFrame(function () {
      modal.classList.add('is-open');
      var firstInput = qs('input, select, textarea, button:not([data-modal-action])', body);
      if (firstInput) firstInput.focus();
    });
  }

  function closeModal() {
    var modal = qs('#profileModal');
    if (!modal || !_modalCurrent) return;
    modal.classList.remove('is-open');
    setTimeout(function () {
      modal.hidden = true;
      qs('#profileModalBody').innerHTML = '';
      document.body.style.overflow = '';
      if (_lastFocused && _lastFocused.focus) _lastFocused.focus();
      _modalCurrent = null;
      _lastFocused = null;
      _pendingPhone = null;
    }, 180);
  }

  // ---------- Email modal ----------
  function renderEmailForm() {
    var current = (_profile && (_profile.vergentEmail || _profile.email)) || '';
    return [
      '<p class="profile-modal-intro">Submit a new email and we\'ll review the request before it takes effect. For your security, this is an account change reviewed by a Cash in Flash specialist.</p>',
      '<div class="profile-modal-current">',
      '  <div class="profile-modal-current-label">Current email</div>',
      '  <div class="profile-modal-current-value">' + escape(current || '—') + '</div>',
      '</div>',
      '<form class="profile-modal-form" id="profileEmailForm" novalidate>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">New email address</span>',
      '    <input type="email" name="email" id="profileEmailInput" autocomplete="email" required maxlength="254" placeholder="you@example.com">',
      '  </label>',
      '  <div class="profile-modal-error" id="profileEmailError" hidden></div>',
      '  <div class="profile-modal-secure">',
      '    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
      '    Reviewed by our team within one business day. We\'ll email you to confirm.',
      '  </div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" data-modal-action="close">Cancel</button>',
      '    <button type="submit" class="btn-apply">Submit request</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function bindEmailForm() {
    qs('#profileEmailForm').addEventListener('submit', submitEmail);
  }

  function submitEmail(ev) {
    ev.preventDefault();
    var input = qs('#profileEmailInput');
    var err = qs('#profileEmailError');
    var btns = qsa('button', qs('#profileEmailForm'));
    var email = (input.value || '').trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      err.textContent = 'Please enter a valid email address.';
      err.hidden = false;
      return;
    }
    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(EMAIL_ENDPOINT, { method: 'PUT', body: { email: email } }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200) {
        banner('ok', 'Email change submitted. Our team will review and confirm with you shortly.');
        markPending('email');
        closeModal();
      } else if (r.status === 400 && r.data && r.data.error === 'no_change') {
        err.textContent = "That's the same email we have on file.";
        err.hidden = false;
      } else {
        err.textContent = "We couldn't submit your request right now. Please try again.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  // ---------- Phone modal (two steps) ----------
  function renderPhoneStartForm() {
    var current = (_profile && (_profile.vergentPhone || _profile.phone)) || '';
    return [
      '<p class="profile-modal-intro">Add a new mobile number for sign-in codes and account alerts. We\'ll text a 6-digit code to confirm you have access to the new phone.</p>',
      '<div class="profile-modal-current">',
      '  <div class="profile-modal-current-label">Current phone</div>',
      '  <div class="profile-modal-current-value">' + escape(current ? fmtPhone(current) : '—') + '</div>',
      '</div>',
      '<form class="profile-modal-form" id="profilePhoneForm" novalidate>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">New mobile number</span>',
      '    <input type="tel" name="phone" id="profilePhoneInput" autocomplete="tel" inputmode="numeric" placeholder="(555) 123-4567" maxlength="20" required>',
      '  </label>',
      '  <div class="profile-modal-error" id="profilePhoneError" hidden></div>',
      '  <div class="profile-modal-secure">',
      '    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
      '    We\'ll send a verification code so only you can change this number.',
      '  </div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" data-modal-action="close">Cancel</button>',
      '    <button type="submit" class="btn-apply">Send code</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function renderPhoneCodeForm(maskedPhone) {
    return [
      '<p class="profile-modal-intro">We sent a 6-digit code to <strong>' + escape(maskedPhone || '') + '</strong>. It expires in 10 minutes.</p>',
      '<form class="profile-modal-form" id="profilePhoneCodeForm" novalidate>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">Verification code</span>',
      '    <input type="text" name="code" id="profilePhoneCodeInput" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="one-time-code" required placeholder="123456">',
      '  </label>',
      '  <div class="profile-modal-error" id="profilePhoneCodeError" hidden></div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" id="profilePhoneCodeResend">Use a different number</button>',
      '    <button type="submit" class="btn-apply">Verify and submit</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function bindPhoneStartForm() {
    qs('#profilePhoneForm').addEventListener('submit', submitPhoneStart);
  }

  function bindPhoneCodeForm() {
    qs('#profilePhoneCodeForm').addEventListener('submit', submitPhoneConfirm);
    qs('#profilePhoneCodeResend').addEventListener('click', function () {
      // Re-render the start form so the user can pick a different number.
      _pendingPhone = null;
      qs('#profileModalBody').innerHTML = renderPhoneStartForm();
      bindPhoneStartForm();
      var firstInput = qs('#profilePhoneInput');
      if (firstInput) firstInput.focus();
    });
  }

  function submitPhoneStart(ev) {
    ev.preventDefault();
    var input = qs('#profilePhoneInput');
    var err = qs('#profilePhoneError');
    var btns = qsa('button', qs('#profilePhoneForm'));
    var raw = input.value || '';
    var digits = raw.replace(/\D/g, '');
    if (digits.length === 11 && digits[0] === '1') digits = digits.slice(1);
    if (digits.length !== 10) {
      err.textContent = 'Please enter a 10-digit US mobile number.';
      err.hidden = false;
      return;
    }
    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(PHONE_START_ENDPOINT, {
      method: 'POST',
      body: { phone: digits },
    }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200 && r.data && r.data.ok) {
        _pendingPhone = digits;
        var maskedPhone = r.data.maskedPhone || fmtPhone(digits);
        qs('#profileModalBody').innerHTML = renderPhoneCodeForm(maskedPhone);
        bindPhoneCodeForm();
        var ci = qs('#profilePhoneCodeInput');
        if (ci) ci.focus();
      } else {
        err.textContent = "We couldn't send the code right now. Please try again or call (747) 270-7121.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  function submitPhoneConfirm(ev) {
    ev.preventDefault();
    var input = qs('#profilePhoneCodeInput');
    var err = qs('#profilePhoneCodeError');
    var btns = qsa('button', qs('#profilePhoneCodeForm'));
    var code = (input.value || '').replace(/\D/g, '');
    if (code.length < 4) {
      err.textContent = 'Please enter the code we texted you.';
      err.hidden = false;
      return;
    }
    if (!_pendingPhone) {
      err.textContent = 'Please start over.';
      err.hidden = false;
      return;
    }
    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(PHONE_CONFIRM_ENDPOINT, {
      method: 'POST',
      body: { phone: _pendingPhone, code: code },
    }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200 && r.data && r.data.ok) {
        banner('ok', 'Phone verified and submitted for review. Our team will confirm before it becomes your sign-in number.');
        markPending('phone');
        closeModal();
      } else {
        err.textContent = "That code didn't match. Try again or request a new one.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  // ---------- Address modal ----------
  function renderAddressForm() {
    var a = (_profile && _profile.vergentAddress) || {};
    var current = a.addr1
      ? (a.addr1 + (a.addr2 ? ', ' + a.addr2 : '') + '<br>' +
         [a.city, a.state].filter(Boolean).join(', ') + (a.zip ? ' ' + a.zip : ''))
      : '—';

    var stateOptions = STATES.map(function (st) {
      return '<option value="' + st + '"' + (a.state === st ? ' selected' : '') + '>' + st + '</option>';
    }).join('');

    return [
      '<p class="profile-modal-intro">Update where we send loan paperwork and notices. The change will be reviewed before it\'s applied.</p>',
      '<div class="profile-modal-current">',
      '  <div class="profile-modal-current-label">Current address</div>',
      '  <div class="profile-modal-current-value">' + current + '</div>',
      '</div>',
      '<form class="profile-modal-form" id="profileAddressForm" novalidate>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">Street address</span>',
      '    <input type="text" name="addr1" id="profileAddr1Input" autocomplete="street-address" maxlength="120" required value="' + escape(a.addr1 || '') + '">',
      '  </label>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">Apartment, suite, etc. (optional)</span>',
      '    <input type="text" name="addr2" id="profileAddr2Input" autocomplete="address-line2" maxlength="60" value="' + escape(a.addr2 || '') + '">',
      '  </label>',
      '  <div class="profile-modal-row">',
      '    <label class="profile-modal-field profile-modal-field--grow">',
      '      <span class="profile-modal-field-label">City</span>',
      '      <input type="text" name="city" id="profileCityInput" autocomplete="address-level2" maxlength="80" required value="' + escape(a.city || '') + '">',
      '    </label>',
      '    <label class="profile-modal-field profile-modal-field--narrow">',
      '      <span class="profile-modal-field-label">State</span>',
      '      <select name="state" id="profileStateInput" required>',
      '        <option value="">—</option>',
      stateOptions,
      '      </select>',
      '    </label>',
      '    <label class="profile-modal-field profile-modal-field--narrow">',
      '      <span class="profile-modal-field-label">ZIP</span>',
      '      <input type="text" name="zip" id="profileZipInput" autocomplete="postal-code" inputmode="numeric" pattern="[0-9]{5}(-?[0-9]{4})?" maxlength="10" required value="' + escape(a.zip || '') + '">',
      '    </label>',
      '  </div>',
      '  <div class="profile-modal-error" id="profileAddressError" hidden></div>',
      '  <div class="profile-modal-secure">',
      '    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
      '    Reviewed by our team. We\'ll email you when the new address is on file.',
      '  </div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" data-modal-action="close">Cancel</button>',
      '    <button type="submit" class="btn-apply">Submit request</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function bindAddressForm() {
    qs('#profileAddressForm').addEventListener('submit', submitAddress);
  }

  function submitAddress(ev) {
    ev.preventDefault();
    var err = qs('#profileAddressError');
    var btns = qsa('button', qs('#profileAddressForm'));
    var payload = {
      addr1: qs('#profileAddr1Input').value.trim(),
      addr2: qs('#profileAddr2Input').value.trim(),
      city: qs('#profileCityInput').value.trim(),
      state: (qs('#profileStateInput').value || '').trim().toUpperCase(),
      zip: qs('#profileZipInput').value.trim().replace(/\D/g, ''),
    };
    if (!payload.addr1) { err.textContent = 'Street address is required.'; err.hidden = false; return; }
    if (!payload.city) { err.textContent = 'City is required.'; err.hidden = false; return; }
    if (payload.state.length !== 2) { err.textContent = 'Please choose a state.'; err.hidden = false; return; }
    if (payload.zip.length !== 5 && payload.zip.length !== 9) { err.textContent = 'ZIP must be 5 or 9 digits.'; err.hidden = false; return; }

    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(ADDRESS_ENDPOINT, { method: 'PUT', body: payload }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200) {
        banner('ok', "Address change submitted for review. We'll update it once our team confirms.");
        markPending('address');
        closeModal();
      } else {
        err.textContent = "We couldn't submit your request right now. Please try again.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  // ---------- Pending badge ----------
  function markPending(which) {
    var id = ({ email: '#profileEmailPending', phone: '#profilePhonePending', address: '#profileAddressPending' })[which];
    var el = id ? qs(id) : null;
    if (el) el.hidden = false;
  }

  // ---------- Top-of-page banner ----------
  function banner(kind, msg) {
    var el = qs('#profileBanner');
    if (!el) return;
    el.className = 'dash-banner ' + (kind === 'ok' ? 'dash-banner--ok' : (kind === 'warn' ? 'dash-banner--warn' : 'dash-banner--err'));
    el.textContent = msg;
    el.hidden = false;
    try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
    if (kind === 'ok') {
      setTimeout(function () { if (el) el.hidden = true; }, 6000);
    }
  }
})();
