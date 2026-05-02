/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL · PROFILE
   Self-service edit for email / phone / address.
   Phone update is two-step (Vergent SMS PIN before save).
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

  // ---------- Helpers ----------
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

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

  function setText(el, v) { if (el) el.textContent = v; }

  function fmtPhone(raw) {
    var d = String(raw || '').replace(/\D/g, '');
    if (d.length === 11 && d[0] === '1') d = d.slice(1);
    if (d.length === 10) {
      return '(' + d.slice(0, 3) + ') ' + d.slice(3, 6) + '-' + d.slice(6);
    }
    return raw || '—';
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

  // Local copy of the most recent profile fetch — used by Edit forms
  // to pre-fill from current values.
  var _profile = null;
  var _pendingPhone = null;  // 10-digit phone awaiting code confirmation

  // ---------- Init ----------
  document.addEventListener('DOMContentLoaded', function () {
    var first = (claims.given_name || '').trim();
    setText(qs('#userChip'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    setText(qs('#sidebarUserName'), first ? ('Hi, ' + first) : (claims.email || 'Account'));
    var year = qs('#footerYear');
    if (year) year.textContent = String(new Date().getFullYear());

    wireEditButtons();
    loadProfile();
  });

  function wireEditButtons() {
    qs('[data-action="edit-email"]').addEventListener('click', function () { openEdit('email'); });
    qs('[data-action="cancel-email"]').addEventListener('click', function () { closeEdit('email'); });
    qs('#profileEmailForm').addEventListener('submit', submitEmail);

    qs('[data-action="edit-phone"]').addEventListener('click', function () { openEdit('phone'); });
    qs('[data-action="cancel-phone"]').addEventListener('click', function () { closeEdit('phone'); });
    qs('[data-action="cancel-phone-code"]').addEventListener('click', function () { closeEdit('phone-code'); });
    qs('#profilePhoneForm').addEventListener('submit', submitPhoneStart);
    qs('#profilePhoneCodeForm').addEventListener('submit', submitPhoneConfirm);

    qs('[data-action="edit-address"]').addEventListener('click', function () { openEdit('address'); });
    qs('[data-action="cancel-address"]').addEventListener('click', function () { closeEdit('address'); });
    qs('#profileAddressForm').addEventListener('submit', submitAddress);
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
    // Email
    var email = p.vergentEmail || p.email || '—';
    setText(qs('#profileEmailValue'), email);
    var emailHint = qs('#profileEmailHint');
    if (p.email && p.vergentEmail && p.email.toLowerCase() !== p.vergentEmail.toLowerCase()) {
      emailHint.textContent = 'Sign-in email: ' + p.email;
      emailHint.hidden = false;
    } else {
      emailHint.hidden = true;
    }

    // Phone
    var phone = p.vergentPhone || p.phone || '';
    setText(qs('#profilePhoneValue'), phone ? fmtPhone(phone) : '—');

    // Address
    var addr = p.vergentAddress || null;
    var addrEl = qs('#profileAddressValue');
    if (addr && addr.addr1) {
      var line2 = [addr.city, addr.state, addr.zip].filter(Boolean).join(', ').replace(', ' + (addr.zip || ''), ' ' + (addr.zip || ''));
      addrEl.innerHTML = escape(addr.addr1) + (addr.addr2 ? ', ' + escape(addr.addr2) : '') +
                        '<br>' + escape(line2);
    } else {
      addrEl.textContent = '—';
    }
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  // ---------- Edit panels ----------
  function openEdit(which) {
    if (which === 'email') {
      qs('#profileEmailForm').hidden = false;
      qs('#profileEmailInput').value = (_profile && (_profile.vergentEmail || _profile.email)) || '';
      qs('#profileEmailError').hidden = true;
      qs('#profileEmailInput').focus();
    } else if (which === 'phone') {
      qs('#profilePhoneForm').hidden = false;
      qs('#profilePhoneCodeForm').hidden = true;
      qs('#profilePhoneInput').value = '';
      qs('#profilePhoneError').hidden = true;
      qs('#profilePhoneInput').focus();
    } else if (which === 'address') {
      qs('#profileAddressForm').hidden = false;
      var a = (_profile && _profile.vergentAddress) || {};
      qs('#profileAddr1Input').value = a.addr1 || '';
      qs('#profileAddr2Input').value = a.addr2 || '';
      qs('#profileCityInput').value = a.city || '';
      qs('#profileStateInput').value = a.state || '';
      qs('#profileZipInput').value = a.zip || '';
      qs('#profileAddressError').hidden = true;
      qs('#profileAddr1Input').focus();
    }
  }

  function closeEdit(which) {
    if (which === 'email') qs('#profileEmailForm').hidden = true;
    else if (which === 'phone') {
      qs('#profilePhoneForm').hidden = true;
    } else if (which === 'phone-code') {
      qs('#profilePhoneCodeForm').hidden = true;
      _pendingPhone = null;
    } else if (which === 'address') qs('#profileAddressForm').hidden = true;
  }

  // ---------- Submit handlers ----------
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
        banner('ok', 'Email updated. We sent a confirmation to your new address.');
        if (_profile) _profile.vergentEmail = email;
        renderProfile(_profile);
        closeEdit('email');
      } else {
        err.textContent = 'We couldn’t update your email right now. Please try again.';
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
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
        qs('#profilePhoneForm').hidden = true;
        qs('#profilePhoneCodeForm').hidden = false;
        var hint = qs('#profilePhoneCodeHint');
        if (hint) hint.textContent = 'We sent a code to ' + (r.data.maskedPhone || fmtPhone(digits)) + '.';
        qs('#profilePhoneCodeInput').value = '';
        qs('#profilePhoneCodeError').hidden = true;
        qs('#profilePhoneCodeInput').focus();
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
        if (r.data.savedToProfile === false) {
          banner('warn', "We verified your number but couldn't save it to your account. Please call (747) 270-7121 to finish.");
        } else {
          banner('ok', 'Phone updated. New sign-in codes will go to ' + fmtPhone(_pendingPhone) + '.');
        }
        if (_profile) _profile.vergentPhone = _pendingPhone;
        renderProfile(_profile);
        _pendingPhone = null;
        closeEdit('phone-code');
      } else {
        err.textContent = 'That code didn’t match. Try again or request a new one.';
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
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
    if (payload.state.length !== 2) { err.textContent = 'State must be a 2-letter code.'; err.hidden = false; return; }
    if (payload.zip.length !== 5 && payload.zip.length !== 9) { err.textContent = 'ZIP must be 5 or 9 digits.'; err.hidden = false; return; }

    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(ADDRESS_ENDPOINT, { method: 'PUT', body: payload }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200) {
        banner('ok', 'Mailing address updated.');
        if (_profile) {
          _profile.vergentAddress = {
            addr1: payload.addr1, addr2: payload.addr2,
            city: payload.city, state: payload.state, zip: payload.zip,
          };
        }
        renderProfile(_profile);
        closeEdit('address');
      } else {
        err.textContent = "We couldn't update your address right now. Please try again.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  // ---------- Top-of-page banner ----------
  function banner(kind, msg) {
    var el = qs('#profileBanner');
    if (!el) return;
    el.className = 'dash-banner ' + (kind === 'ok' ? 'dash-banner--ok' : (kind === 'warn' ? 'dash-banner--warn' : 'dash-banner--err'));
    el.textContent = msg;
    el.hidden = false;
    // Scroll to top so the user sees it.
    try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
    // Auto-hide success after 6s; keep errors until next action.
    if (kind === 'ok') {
      setTimeout(function () { if (el) el.hidden = true; }, 6000);
    }
  }
})();
