/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL · PROFILE
   Banking-style profile page. Each row opens a modal sheet for
   intentional, reviewed edits. Phone is two-step (Telnyx Verify).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var API_BASE = '/api';
  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/login.html';
  var PROFILE_ENDPOINT = API_BASE + '/my-profile';
  var EMAIL_ENDPOINT = API_BASE + '/my-profile/email';
  var EMAIL_START_ENDPOINT = API_BASE + '/my-profile/email/start-verify';
  var EMAIL_CONFIRM_ENDPOINT = API_BASE + '/my-profile/email/confirm';
  var PASSWORD_ENDPOINT = API_BASE + '/my-profile/password';
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
  var _pendingEmail = null;        // candidate new email awaiting code confirmation
  var _pendingEmailRequestId = null;
  var _modalCurrent = null;        // which edit type is open ('email' | 'phone' | 'address')
  var _lastFocused = null;         // restore focus on modal close

  // ---------- Init ----------
  document.addEventListener('DOMContentLoaded', function () {
    // The app shell (sidebar.js) fills #sidebarUserName + .dash-first-name.
    var year = qs('#footerYear');
    if (year) year.textContent = String(new Date().getFullYear());

    wireRows();
    wireModal();
    loadProfile();
  });

  function wireRows() {
    // Hub tiles (and any legacy rows) carrying data-edit open their modal.
    qsa('[data-edit]').forEach(function (row) {
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
    // Delegate so dynamically-rendered Cancel/Close buttons work too.
    modal.addEventListener('click', function (ev) {
      var t = ev.target.closest ? ev.target.closest('[data-modal-action="close"]') : null;
      if (t) { ev.preventDefault(); closeModal(); }
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
    // The settings hub doesn't display these inline — the edit modals read
    // _profile directly for their "current value" displays. Just cache it.
    _profile = p || {};
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
    } else if (which === 'password') {
      title.textContent = 'Change password';
      body.innerHTML = renderPasswordForm();
      bindPasswordForm();
    } else if (which === 'personal') {
      title.textContent = 'Personal info';
      body.innerHTML = renderPersonalView();
      bindPersonalView();
    } else if (which === 'contact') {
      title.textContent = 'Contact details';
      body.innerHTML = renderContactView();
      bindContactView();
    } else if (which === 'notifications') {
      title.textContent = 'Notifications';
      body.innerHTML = renderNotificationsView();
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
      _pendingEmail = null;
      _pendingEmailRequestId = null;
    }, 180);
  }

  // ---------- Personal info (read-only identity + address edit entry) ----------
  function renderPersonalView() {
    var p = _profile || {};
    var first = (p.firstName || claims.given_name || '').trim();
    var last = (p.lastName || claims.family_name || '').trim();
    var name = (first + ' ' + last).trim() || '—';
    var dob = p.dob || p.dateOfBirth || p.vergentDob || '';
    var a = p.vergentAddress || {};
    var addr = a.addr1
      ? (escape(a.addr1) + (a.addr2 ? ', ' + escape(a.addr2) : '') + '<br>' +
         escape([a.city, a.state].filter(Boolean).join(', ')) + (a.zip ? ' ' + escape(a.zip) : ''))
      : '—';
    return [
      '<p class="profile-modal-intro">Your name and date of birth are verified when you sign up — call us at (888) 999-9859 to change them. You can update your home address below.</p>',
      '<div class="profile-modal-current"><div class="profile-modal-current-label">Full name</div><div class="profile-modal-current-value">' + escape(name) + '</div></div>',
      (dob ? '<div class="profile-modal-current"><div class="profile-modal-current-label">Date of birth</div><div class="profile-modal-current-value">' + escape(dob) + '</div></div>' : ''),
      '<div class="profile-modal-current"><div class="profile-modal-current-label">Home address</div><div class="profile-modal-current-value">' + addr + '</div></div>',
      '<div class="profile-modal-actions"><button type="button" class="btn-text" data-modal-action="close">Close</button><button type="button" class="btn-apply" id="profilePersonalEditAddr">Update home address</button></div>',
    ].join('');
  }
  function bindPersonalView() {
    var b = qs('#profilePersonalEditAddr');
    if (b) b.addEventListener('click', function () { openModal('address'); });
  }

  // ---------- Contact details (email + phone entry points) ----------
  function renderContactView() {
    var p = _profile || {};
    var email = p.vergentEmail || p.email || '—';
    var phone = (p.vergentPhone || p.phone || '');
    return [
      '<p class="profile-modal-intro">Manage the email and phone number we use for account notices and secure sign-in codes.</p>',
      '<div class="profile-contact-item">',
      '  <div class="profile-modal-current-label">Email address</div>',
      '  <div class="profile-contact-row"><span class="profile-modal-current-value">' + escape(email) + '</span>',
      '    <button type="button" class="btn-text" id="profileContactEditEmail">Update</button></div>',
      '</div>',
      '<div class="profile-contact-item">',
      '  <div class="profile-modal-current-label">Mobile phone</div>',
      '  <div class="profile-contact-row"><span class="profile-modal-current-value">' + escape(phone ? fmtPhone(phone) : '—') + '</span>',
      '    <button type="button" class="btn-text" id="profileContactEditPhone">Update</button></div>',
      '</div>',
      '<div class="profile-modal-actions"><button type="button" class="btn-text" data-modal-action="close">Close</button></div>',
    ].join('');
  }
  function bindContactView() {
    var e = qs('#profileContactEditEmail');
    var ph = qs('#profileContactEditPhone');
    if (e) e.addEventListener('click', function () { openModal('email'); });
    if (ph) ph.addEventListener('click', function () { openModal('phone'); });
  }

  // ---------- Notifications (informational; preferences coming soon) ----------
  function renderNotificationsView() {
    return [
      '<p class="profile-modal-intro">Choose how we reach you. Today we send important account and payment updates by email and text so you never miss a due date. Custom preferences are coming soon.</p>',
      '<ul class="profile-notif-list">',
      '  <li><span>Payment reminders</span><span class="profile-row-badge profile-row-badge--ok">On</span></li>',
      '  <li><span>Account &amp; security alerts</span><span class="profile-row-badge profile-row-badge--ok">On</span></li>',
      '  <li><span>Loan offers &amp; news</span><span class="profile-row-badge profile-row-badge--ok">On</span></li>',
      '</ul>',
      '<div class="profile-modal-actions"><button type="button" class="btn-apply" data-modal-action="close">Got it</button></div>',
    ].join('');
  }

  // ---------- Email modal (two steps: candidate → code) ----------
  function renderEmailStartForm() {
    var current = (_profile && (_profile.vergentEmail || _profile.email)) || '';
    return [
      '<p class="profile-modal-intro">Add a new email for account notices and sign-in. We\'ll send a 6-digit code to confirm you have access to the new address.</p>',
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
      '    We\'ll email a verification code so only you can change this address.',
      '  </div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" data-modal-action="close">Cancel</button>',
      '    <button type="submit" class="btn-apply">Send code</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function renderEmailCodeForm(maskedEmail) {
    return [
      '<p class="profile-modal-intro">We sent a 6-digit code to <strong>' + escape(maskedEmail || '') + '</strong>. It expires in 10 minutes.</p>',
      '<form class="profile-modal-form" id="profileEmailCodeForm" novalidate>',
      '  <label class="profile-modal-field">',
      '    <span class="profile-modal-field-label">Verification code</span>',
      '    <input type="text" name="code" id="profileEmailCodeInput" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" required placeholder="123456">',
      '  </label>',
      '  <div class="profile-modal-error" id="profileEmailCodeError" hidden></div>',
      '  <div class="profile-modal-actions">',
      '    <button type="button" class="btn-text" id="profileEmailCodeRetry">Use a different email</button>',
      '    <button type="submit" class="btn-apply">Verify and submit</button>',
      '  </div>',
      '</form>',
    ].join('');
  }

  function renderEmailForm() {
    return renderEmailStartForm();
  }

  function bindEmailForm() {
    qs('#profileEmailForm').addEventListener('submit', submitEmailStart);
  }

  function bindEmailCodeForm() {
    qs('#profileEmailCodeForm').addEventListener('submit', submitEmailConfirm);
    qs('#profileEmailCodeRetry').addEventListener('click', function () {
      _pendingEmail = null;
      _pendingEmailRequestId = null;
      qs('#profileModalBody').innerHTML = renderEmailStartForm();
      bindEmailForm();
      var firstInput = qs('#profileEmailInput');
      if (firstInput) firstInput.focus();
    });
  }

  function submitEmailStart(ev) {
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
    apiFetch(EMAIL_START_ENDPOINT, { method: 'POST', body: { email: email } }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200 && r.data && r.data.ok) {
        _pendingEmail = email;
        _pendingEmailRequestId = r.data.requestId;
        var maskedEmail = r.data.maskedEmail || email;
        qs('#profileModalBody').innerHTML = renderEmailCodeForm(maskedEmail);
        bindEmailCodeForm();
        var ci = qs('#profileEmailCodeInput');
        if (ci) ci.focus();
      } else if (r.status === 400 && r.data && r.data.error === 'no_change') {
        err.textContent = "That's the same email we have on file.";
        err.hidden = false;
      } else {
        err.textContent = "We couldn't send the code right now. Please try again or call (888) 999-9859.";
        err.hidden = false;
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      err.textContent = 'Network error. Please try again.';
      err.hidden = false;
    });
  }

  function submitEmailConfirm(ev) {
    ev.preventDefault();
    var input = qs('#profileEmailCodeInput');
    var err = qs('#profileEmailCodeError');
    var btns = qsa('button', qs('#profileEmailCodeForm'));
    var code = (input.value || '').replace(/\D/g, '');
    if (code.length < 4) {
      err.textContent = 'Please enter the code we emailed you.';
      err.hidden = false;
      return;
    }
    if (!_pendingEmailRequestId) {
      err.textContent = 'Please start over.';
      err.hidden = false;
      return;
    }
    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });
    apiFetch(EMAIL_CONFIRM_ENDPOINT, {
      method: 'POST',
      body: { requestId: _pendingEmailRequestId, code: code },
    }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      if (r.status === 200 && r.data && r.data.ok) {
        if (r.data.status === 'applied') {
          banner('ok', 'Your email has been updated. We just sent a confirmation to your new address.');
        } else {
          banner('ok', 'Email verified and submitted for review. Our team will confirm before it becomes your sign-in email.');
          markPending('email');
        }
        _pendingEmail = null;
        _pendingEmailRequestId = null;
        // Refresh the profile rows so the new email shows up if it's
        // already live (auto-apply path). On the queued path the page
        // value stays the same and the pending pill is shown.
        loadProfile();
        closeModal();
      } else if (r.status === 400 && r.data && r.data.error === 'too_many_attempts') {
        err.textContent = 'Too many incorrect attempts. Please start over.';
        err.hidden = false;
      } else if (r.status === 400 && r.data && (r.data.error === 'session_expired' || r.data.error === 'session_state')) {
        err.textContent = 'That session has expired. Please start over.';
        err.hidden = false;
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
        err.textContent = "We couldn't send the code right now. Please try again or call (888) 999-9859.";
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

  // ---------- Change password modal ----------
  // Banking-style flow: live requirement checklist, show/hide toggles,
  // server-side re-auth + policy enforcement, security alert email
  // on success.
  function passwordFieldHtml(opts) {
    // opts: { id, name, label, autocomplete, hint }
    return [
      '<label class="profile-modal-field">',
      '  <span class="profile-modal-field-label">' + escape(opts.label) + '</span>',
      '  <span class="pw-input-wrap">',
      '    <input type="password" name="' + opts.name + '" id="' + opts.id + '" autocomplete="' + (opts.autocomplete || 'off') + '" required maxlength="128">',
      '    <button type="button" class="pw-toggle" data-pw-toggle="' + opts.id + '" aria-label="Show password" aria-pressed="false">',
      '      <svg class="pw-eye" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
      '    </button>',
      '  </span>',
      (opts.hint ? '  <span class="profile-modal-field-hint">' + escape(opts.hint) + '</span>' : ''),
      '</label>',
    ].join('');
  }

  function renderPasswordForm() {
    return [
      '<p class="profile-modal-intro">For your security, enter your current password before choosing a new one. We\'ll email you a confirmation as soon as the change is applied.</p>',
      '<form class="profile-modal-form" id="profilePasswordForm" novalidate>',
      passwordFieldHtml({
        id: 'profilePasswordCurrent',
        name: 'currentPassword',
        label: 'Current password',
        autocomplete: 'current-password',
      }),
      passwordFieldHtml({
        id: 'profilePasswordNew',
        name: 'newPassword',
        label: 'New password',
        autocomplete: 'new-password',
      }),
      '<ul class="pw-checklist" id="profilePasswordChecklist" aria-live="polite">',
      '  <li data-rule="length"><span class="pw-check-dot" aria-hidden="true"></span>At least 12 characters</li>',
      '  <li data-rule="upper"><span class="pw-check-dot" aria-hidden="true"></span>One uppercase letter</li>',
      '  <li data-rule="lower"><span class="pw-check-dot" aria-hidden="true"></span>One lowercase letter</li>',
      '  <li data-rule="digit"><span class="pw-check-dot" aria-hidden="true"></span>One number</li>',
      '  <li data-rule="different"><span class="pw-check-dot" aria-hidden="true"></span>Different from your current password</li>',
      '</ul>',
      passwordFieldHtml({
        id: 'profilePasswordConfirm',
        name: 'confirmPassword',
        label: 'Confirm new password',
        autocomplete: 'new-password',
      }),
      '<div class="profile-modal-error" id="profilePasswordError" hidden></div>',
      '<div class="profile-modal-secure">',
      '  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
      '  Your other active sign-ins stay active. We\'ll email a confirmation as soon as the change applies.',
      '</div>',
      '<div class="profile-modal-actions profile-modal-actions--split">',
      '  <a href="/forgot.html" class="btn-text">Forgot current password?</a>',
      '  <div class="profile-modal-actions-right">',
      '    <button type="button" class="btn-text" data-modal-action="close">Cancel</button>',
      '    <button type="submit" class="btn-apply" id="profilePasswordSubmit" disabled>Update password</button>',
      '  </div>',
      '</div>',
      '</form>',
    ].join('');
  }

  function pwRules(current, next) {
    return {
      length:    next.length >= 12,
      upper:     /[A-Z]/.test(next),
      lower:     /[a-z]/.test(next),
      digit:     /[0-9]/.test(next),
      different: !!next && next !== current,
    };
  }

  function updatePasswordChecklist() {
    var current = (qs('#profilePasswordCurrent') || {}).value || '';
    var next = (qs('#profilePasswordNew') || {}).value || '';
    var confirm = (qs('#profilePasswordConfirm') || {}).value || '';
    var rules = pwRules(current, next);
    qsa('#profilePasswordChecklist li').forEach(function (li) {
      var rule = li.getAttribute('data-rule');
      if (rules[rule]) li.classList.add('is-met');
      else li.classList.remove('is-met');
    });
    var allRulesMet = rules.length && rules.upper && rules.lower && rules.digit && rules.different;
    var matchOk = next && next === confirm;
    var btn = qs('#profilePasswordSubmit');
    if (btn) btn.disabled = !(current && allRulesMet && matchOk);
  }

  function bindPasswordForm() {
    qs('#profilePasswordForm').addEventListener('submit', submitPassword);
    ['profilePasswordCurrent', 'profilePasswordNew', 'profilePasswordConfirm'].forEach(function (id) {
      var el = qs('#' + id);
      if (el) el.addEventListener('input', updatePasswordChecklist);
    });
    qsa('[data-pw-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var targetId = btn.getAttribute('data-pw-toggle');
        var input = qs('#' + targetId);
        if (!input) return;
        var showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        btn.setAttribute('aria-pressed', showing ? 'false' : 'true');
        btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
        btn.classList.toggle('is-on', !showing);
      });
    });
    updatePasswordChecklist();
  }

  function submitPassword(ev) {
    ev.preventDefault();
    var current = qs('#profilePasswordCurrent').value || '';
    var next = qs('#profilePasswordNew').value || '';
    var confirm = qs('#profilePasswordConfirm').value || '';
    var err = qs('#profilePasswordError');
    var btns = qsa('button[type="submit"], button[type="button"][data-modal-action="close"]', qs('#profilePasswordForm'));

    function fail(msg) {
      err.textContent = msg;
      err.hidden = false;
    }

    if (!current || !next || !confirm) {
      fail('Please fill in all three fields.');
      return;
    }
    if (next !== confirm) {
      fail("New password and confirmation don't match.");
      return;
    }
    var rules = pwRules(current, next);
    if (!rules.different) { fail('Your new password must be different from the current one.'); return; }
    if (!rules.length) { fail('New password must be at least 12 characters long.'); return; }
    if (!rules.upper) { fail('New password must include an uppercase letter.'); return; }
    if (!rules.lower) { fail('New password must include a lowercase letter.'); return; }
    if (!rules.digit) { fail('New password must include a number.'); return; }

    err.hidden = true;
    btns.forEach(function (b) { b.disabled = true; });

    apiFetch(PASSWORD_ENDPOINT, {
      method: 'POST',
      body: { currentPassword: current, newPassword: next },
    }).then(function (r) {
      btns.forEach(function (b) { b.disabled = false; });
      updatePasswordChecklist();
      if (r.status === 200 && r.data && r.data.ok) {
        banner('ok', 'Password updated. We just emailed you a confirmation.');
        closeModal();
        return;
      }
      var code = (r.data && r.data.error) || '';
      if (r.status === 400 && code === 'current_password_incorrect') {
        fail("That current password isn't right. Try again.");
        var cur = qs('#profilePasswordCurrent');
        if (cur) { cur.value = ''; cur.focus(); }
      } else if (r.status === 400 && code === 'same_password') {
        fail('Your new password must be different from the current one.');
      } else if (r.status === 400 && code === 'policy_violation') {
        fail("That password doesn't meet our requirements. Try a longer one with mixed characters.");
      } else if (r.status === 400 && code === 'reset_required') {
        fail('Your account requires a password reset. Use the "Forgot current password?" link.');
      } else if (r.status === 400 && code.indexOf('needs_') === 0 || code.indexOf('too_') === 0) {
        var map = {
          too_short: 'New password must be at least 12 characters long.',
          too_long: 'New password is too long.',
          needs_uppercase: 'New password must include an uppercase letter.',
          needs_lowercase: 'New password must include a lowercase letter.',
          needs_digit: 'New password must include a number.',
        };
        fail(map[code] || 'Please choose a stronger password.');
      } else if (r.status === 429) {
        fail('Too many attempts. Please wait a few minutes and try again.');
      } else {
        fail("We couldn't update your password right now. Please try again.");
      }
    }).catch(function (e) {
      btns.forEach(function (b) { b.disabled = false; });
      if (e && e.message === 'unauthorized') return;
      fail('Network error. Please try again.');
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
