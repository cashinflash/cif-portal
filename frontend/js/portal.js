/*
 * Shared portal JS helpers.
 * Keeps auth, fetch wrapper, and session state in one place.
 * Loaded by every portal page via <script src="/js/portal.js"></script>.
 */

const PORTAL = (() => {
  const API_BASE = ''; // same origin — API Gateway routed through CloudFront /api/*

  // Cognito public config for the dev stage. These IDs are public by design
  // (the client has no secret and the pool ID appears in every JWT iss claim).
  // If we add a prod stage later, swap these at deploy time via a generated
  // config.js file — for now, dev is the only stage so we hardcode.
  const COGNITO = {
    region:     'us-east-1',
    userPoolId: 'us-east-1_U508xOs95',
    clientId:   '1mddi61n19hftaldt9t3r622b',
  };

  // Direct REST call to Cognito's unsigned user-pool endpoint.
  // We use USER_PASSWORD_AUTH (enabled on the app client) so no SRP math
  // is needed client-side. The app client has no secret, so no SECRET_HASH.
  async function cognitoCall(target, body) {
    const resp = await fetch(`https://cognito-idp.${COGNITO.region}.amazonaws.com/`, {
      method: 'POST',
      headers: {
        'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
        'Content-Type': 'application/x-amz-json-1.1',
      },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.message || data.Message || data.__type || resp.statusText);
      err.code = (data.__type || '').split('#').pop() || resp.statusText;
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  // ───────── Impersonation bootstrap ─────────
  // When cif-dashboard opens a "View as customer" tab, the URL ends in
  // a fragment like:
  //   #impersonationToken=<T>&jwt=<J>&name=<N>&cid=<C>&exp=<unix>
  // We pull those values out of the fragment, stash them in
  // sessionStorage, then strip the fragment so a refresh doesn't
  // re-process the same token. The JWT lands in cif_id_token so
  // apiFetch's normal Authorization header path works untouched;
  // the impersonation token gets sent as X-Impersonation-Token on
  // every request so the customer Lambdas know to scope data to the
  // target customer (and reject writes).
  function _bootstrapImpersonationFromHash() {
    try {
      const hash = window.location.hash || '';
      if (!hash || hash.indexOf('impersonationToken=') < 0) return;
      const params = new URLSearchParams(hash.startsWith('#') ? hash.slice(1) : hash);
      const impToken = params.get('impersonationToken');
      if (!impToken) return;
      const jwt = params.get('jwt') || '';
      const name = params.get('name') || '';
      const cid = params.get('cid') || '';
      const email = params.get('email') || '';
      const exp = parseInt(params.get('exp') || '0', 10) || 0;
      // Save BEFORE scrubbing — if anything throws the URL still has
      // the token and the user can refresh to retry.
      sessionStorage.setItem('cif_impersonation_token', impToken);
      sessionStorage.setItem('cif_impersonation_meta', JSON.stringify({
        name, cid, email, exp,
      }));
      if (jwt) sessionStorage.setItem('cif_id_token', jwt);
      // Strip the fragment from the URL bar so the token isn't
      // visible to over-the-shoulder snoopers and a refresh doesn't
      // try to re-bootstrap. replaceState because we don't want
      // history entry for the token-bearing URL.
      const cleanUrl = window.location.pathname + window.location.search;
      window.history.replaceState(null, '', cleanUrl);
    } catch (e) {
      console.warn('impersonation bootstrap failed', e);
    }
  }

  _bootstrapImpersonationFromHash();

  async function apiFetch(path, opts = {}) {
    const token = sessionStorage.getItem('cif_id_token') || '';
    const impToken = sessionStorage.getItem('cif_impersonation_token') || '';
    const headers = Object.assign(
      { 'Content-Type': 'application/json' },
      opts.headers || {}
    );
    if (token) headers.Authorization = `Bearer ${token}`;
    // When viewing as a customer, every request carries this header
    // alongside the normal Authorization. Customer Lambdas read it
    // and synthesize claims for the target customer (the operator's
    // own JWT just satisfies the API Gateway authorizer). Writes are
    // blocked server-side; the banner UI also hides the buttons.
    if (impToken) headers['X-Impersonation-Token'] = impToken;

    const resp = await fetch(API_BASE + path, {
      ...opts,
      headers,
      credentials: 'same-origin',
    });

    if (resp.status === 401) {
      // expired/invalid — kick to login
      sessionStorage.removeItem('cif_id_token');
      window.location.href = '/login.html';
      return;
    }

    const contentType = resp.headers.get('content-type') || '';
    const body = contentType.includes('application/json')
      ? await resp.json()
      : await resp.text();

    if (!resp.ok) {
      const err = new Error(body.error || body.message || resp.statusText);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function setToken(idToken) {
    sessionStorage.setItem('cif_id_token', idToken);
  }

  function getToken() {
    return sessionStorage.getItem('cif_id_token');
  }

  function logout() {
    sessionStorage.removeItem('cif_id_token');
    window.location.href = '/';
  }

  function requireAuth() {
    if (!getToken()) {
      window.location.href = '/login.html';
      return false;
    }
    return true;
  }

  function formatMoney(cents) {
    const dollars = (cents / 100).toFixed(2);
    return `$${dollars}`;
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // High-level Cognito helpers used by signup.html and login.html.
  const cognito = {
    async signUp({ email, password, firstName, lastName, vergentCustomerId }) {
      const attrs = [{ Name: 'email', Value: email }];
      if (firstName) attrs.push({ Name: 'given_name', Value: firstName });
      if (lastName)  attrs.push({ Name: 'family_name', Value: lastName });
      if (vergentCustomerId) attrs.push({ Name: 'custom:vergentCustomerId', Value: String(vergentCustomerId) });
      return cognitoCall('SignUp', {
        ClientId: COGNITO.clientId,
        Username: email,
        Password: password,
        UserAttributes: attrs,
      });
    },
    async confirmSignUp({ email, code }) {
      return cognitoCall('ConfirmSignUp', {
        ClientId: COGNITO.clientId,
        Username: email,
        ConfirmationCode: code,
      });
    },
    async resendCode({ email }) {
      return cognitoCall('ResendConfirmationCode', {
        ClientId: COGNITO.clientId,
        Username: email,
      });
    },
    // Server-side MFA flow: password is verified on the backend and Cognito tokens
    // are held in DynamoDB until the user enters the email / SMS code. This means
    // the page that calls signIn() *will not* receive tokens — it receives an
    // mfaSession + a list of channels. Then call sendMfaCode() and verifyMfaCode().
    async signIn({ email, password }) {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) {
        const err = new Error(data.error === 'invalid_credentials'
          ? 'That email or password is incorrect.'
          : (data.error || 'unauthorized'));
        err.code = 'NotAuthorizedException';
        throw err;
      }
      if (!r.ok) {
        const err = new Error(data.error || 'Sign-in failed.');
        err.code = data.error || 'AuthFailed';
        throw err;
      }
      return data; // { mfaSession, channels:[...], deliveredTo, expiresInSec }
    },

    async sendMfaCode({ mfaSession, channel }) {
      const r = await fetch('/api/auth/send-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfaSession, channel }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const err = new Error(data.error || 'Could not send code.');
        err.code = data.error || 'SendFailed';
        throw err;
      }
      return data;
    },

    async verifyMfaCode({ mfaSession, code }) {
      const r = await fetch('/api/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfaSession, code }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const err = new Error(data.error || 'Invalid code.');
        err.code = data.error || 'VerifyFailed';
        err.attemptsRemaining = data.attemptsRemaining;
        throw err;
      }
      // Same shape as USER_PASSWORD_AUTH success: store tokens, let caller redirect.
      sessionStorage.setItem('cif_id_token', data.idToken);
      sessionStorage.setItem('cif_access_token', data.accessToken);
      if (data.refreshToken) sessionStorage.setItem('cif_refresh_token', data.refreshToken);
      return data;
    },
  };

  // ───────── Impersonation helpers + banner ─────────
  function getImpersonation() {
    const token = sessionStorage.getItem('cif_impersonation_token') || '';
    if (!token) return null;
    let meta = {};
    try {
      meta = JSON.parse(sessionStorage.getItem('cif_impersonation_meta') || '{}');
    } catch (e) { /* ignore */ }
    return { token, name: meta.name || '', cid: meta.cid || '',
             email: meta.email || '', exp: meta.exp || 0 };
  }

  async function endImpersonation() {
    const imp = getImpersonation();
    if (!imp) return;
    // Best-effort: revoke server-side. Either way, clear local state
    // and navigate away so the operator can't keep using stale data.
    try {
      await fetch('/api/admin/end-impersonate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Impersonation-Token': imp.token,
          // Send the operator's own JWT too so API Gateway authorizer
          // accepts the call.
          'Authorization': `Bearer ${sessionStorage.getItem('cif_id_token') || ''}`,
        },
        body: JSON.stringify({ token: imp.token }),
      });
    } catch (e) { /* ignore — local cleanup matters more */ }
    sessionStorage.removeItem('cif_impersonation_token');
    sessionStorage.removeItem('cif_impersonation_meta');
    sessionStorage.removeItem('cif_id_token');
    // Try to close the tab (works if it was opened by window.open).
    // Browsers block window.close() on tabs the script didn't open,
    // so fall back to redirecting to about:blank.
    try { window.close(); } catch (e) { /* ignore */ }
    window.location.href = 'about:blank';
  }

  function _renderImpersonationBanner() {
    const imp = getImpersonation();
    if (!imp) return;
    if (document.getElementById('cif-impersonation-banner')) return;

    const bar = document.createElement('div');
    bar.id = 'cif-impersonation-banner';
    bar.style.cssText = [
      'position:sticky', 'top:0', 'z-index:9999',
      'background:#5a0d0d', 'color:#fff', 'font-family:inherit',
      'font-size:13px', 'font-weight:600',
      'padding:10px 16px', 'display:flex', 'align-items:center',
      'gap:12px', 'flex-wrap:wrap',
      'box-shadow:0 2px 6px rgba(0,0,0,.2)',
    ].join(';');

    const label = document.createElement('div');
    label.style.cssText = 'flex:1;min-width:200px';
    const who = imp.name ? `<b>${imp.name}</b>` : `Customer #${imp.cid}`;
    const cidPart = imp.cid ? ` · #${imp.cid}` : '';
    label.innerHTML = `⚠️ VIEWING AS CUSTOMER: ${who}${cidPart} <span style="opacity:.7;margin-left:6px">(read-only)</span>`;

    const expSpan = document.createElement('span');
    expSpan.id = 'cif-imp-expiry';
    expSpan.style.cssText = 'font-size:11px;opacity:.8;font-weight:500';

    const endBtn = document.createElement('button');
    endBtn.type = 'button';
    endBtn.textContent = 'End now';
    endBtn.style.cssText = [
      'background:#fff', 'color:#5a0d0d', 'border:none',
      'border-radius:6px', 'padding:6px 14px',
      'font-size:12px', 'font-weight:700', 'font-family:inherit',
      'cursor:pointer',
    ].join(';');
    endBtn.addEventListener('click', endImpersonation);

    bar.appendChild(label);
    bar.appendChild(expSpan);
    bar.appendChild(endBtn);
    document.body.insertBefore(bar, document.body.firstChild);

    // Hide write controls — best-effort UX layer; the real
    // enforcement is the customer-Lambda write-block.
    const style = document.createElement('style');
    style.textContent = `
      #cif-impersonation-banner ~ * form button[type="submit"]:not([data-allow-impersonation]),
      #cif-impersonation-banner ~ * .btn-primary:not([data-allow-impersonation]),
      #cif-impersonation-banner ~ * .btn-danger:not([data-allow-impersonation]) {
        opacity: .35 !important;
        pointer-events: none !important;
        cursor: not-allowed !important;
      }
    `;
    document.head.appendChild(style);

    // Live countdown to expiry.
    function tick() {
      if (!imp.exp) {
        expSpan.textContent = '';
        return;
      }
      const remaining = Math.max(0, imp.exp - Math.floor(Date.now() / 1000));
      if (remaining === 0) {
        endImpersonation();
        return;
      }
      const m = Math.floor(remaining / 60);
      const s = remaining % 60;
      expSpan.textContent = `expires in ${m}:${s < 10 ? '0' : ''}${s}`;
    }
    tick();
    setInterval(tick, 1000);
  }

  // ---------- Show/hide eye toggle on every password field ----------
  // Self-contained: injects its own CSS and wraps each password input, so
  // it works on the gate pages (portal.css, not dashboard.css) without
  // touching their markup. Skips autocomplete="off" fields (masked SSN)
  // and anything marked [data-no-eye].
  var _PW_EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  var _PW_EYE_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20C5 20 1 12 1 12a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

  function _injectPwEyeCss() {
    if (document.getElementById('cif-pw-eye-css')) return;
    var st = document.createElement('style');
    st.id = 'cif-pw-eye-css';
    st.textContent =
      '.cif-pw-wrap{position:relative;display:block}' +
      '.cif-pw-wrap>input{width:100%;box-sizing:border-box;padding-right:48px}' +
      '.cif-pw-toggle{position:absolute;top:0;bottom:0;right:4px;margin:auto 0;height:44px;width:44px;' +
      'display:inline-flex;align-items:center;justify-content:center;padding:0;border:0;background:none;' +
      'color:#94a3b8;cursor:pointer;border-radius:8px;transition:color .15s ease}' +
      '.cif-pw-toggle:hover{color:#475569}.cif-pw-toggle.is-on{color:#0E8741}';
    document.head.appendChild(st);
  }

  function _initPasswordEyes(root) {
    _injectPwEyeCss();
    var scope = (root && root.querySelectorAll) ? root : document;
    Array.prototype.forEach.call(scope.querySelectorAll('input[type="password"]'), function (inp) {
      if (inp.getAttribute('autocomplete') === 'off') return;
      if (inp.getAttribute('data-no-eye') !== null) return;
      if (inp.dataset.cifEye) return;
      inp.dataset.cifEye = '1';
      var wrap = document.createElement('span');
      wrap.className = 'cif-pw-wrap';
      inp.parentNode.insertBefore(wrap, inp);
      wrap.appendChild(inp);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cif-pw-toggle';
      btn.setAttribute('aria-label', 'Show password');
      btn.setAttribute('aria-pressed', 'false');
      btn.innerHTML = _PW_EYE;
      btn.addEventListener('click', function () {
        var showing = inp.type === 'text';
        inp.type = showing ? 'password' : 'text';
        btn.innerHTML = showing ? _PW_EYE : _PW_EYE_OFF;
        btn.classList.toggle('is-on', !showing);
        btn.setAttribute('aria-pressed', showing ? 'false' : 'true');
        btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
        inp.focus();
      });
      wrap.appendChild(btn);
    });
  }

  // ---------- Reusable segmented code (OTP) input ----------
  // Upgrades a single <input> (the value store the page already reads)
  // into N single-digit boxes. Mobile-aware CSS. Returns {focus, clear}.
  function _injectOtpCss() {
    if (document.getElementById('cif-otp-css')) return;
    var st = document.createElement('style');
    st.id = 'cif-otp-css';
    st.textContent =
      '.cif-otp{display:flex;gap:8px}' +
      '.cif-otp-box{flex:1 1 0;min-width:0;height:62px;text-align:center;font-size:2rem;font-weight:700;' +
      'font-family:inherit;color:#0f172a;background:#fff;border:1.5px solid #d4dae3;border-radius:12px;' +
      '-moz-appearance:textfield;transition:border-color .15s ease,box-shadow .15s ease}' +
      '.cif-otp-box::-webkit-outer-spin-button,.cif-otp-box::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}' +
      '.cif-otp-box.filled{border-color:#0E8741}' +
      '.cif-otp-box:focus{outline:none;border-color:#0E8741;box-shadow:0 0 0 3px rgba(14,135,65,.15)}' +
      '@media (max-width:400px){.cif-otp{gap:6px}.cif-otp-box{height:56px;font-size:1.65rem;border-radius:10px}}';
    document.head.appendChild(st);
  }

  function _initOtp(input, opts) {
    opts = opts || {};
    if (!input) return null;
    _injectOtpCss();
    var len = opts.length || parseInt(input.getAttribute('maxlength'), 10) || 6;
    if (input._otp) {
      // Already built. Same length → just reset. Different length (e.g. the
      // user switched email↔SMS) → tear down and rebuild.
      if (input._otp.length === len) { input._otp.clear(); return input._otp; }
      if (input._otp.el && input._otp.el.parentNode) { input._otp.el.parentNode.removeChild(input._otp.el); }
      input._otp = null;
    }
    var wrap = document.createElement('div');
    wrap.className = 'cif-otp';
    var boxes = [];
    for (var i = 0; i < len; i++) {
      var b = document.createElement('input');
      b.type = 'text';
      b.setAttribute('inputmode', 'numeric');
      b.maxLength = 1;
      b.className = 'cif-otp-box';
      b.setAttribute('aria-label', 'Digit ' + (i + 1));
      if (i === 0) b.setAttribute('autocomplete', 'one-time-code');
      wrap.appendChild(b);
      boxes.push(b);
    }
    input.type = 'hidden';
    input.parentNode.insertBefore(wrap, input);
    function sync() {
      input.value = boxes.map(function (b) { return b.value; }).join('');
      boxes.forEach(function (b) { b.classList.toggle('filled', !!b.value); });
      try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
    }
    boxes.forEach(function (box, i) {
      box.addEventListener('input', function () {
        box.value = box.value.replace(/\D/g, '').slice(0, 1);
        if (box.value && i < len - 1) boxes[i + 1].focus();
        sync();
      });
      box.addEventListener('keydown', function (e) {
        if (e.key === 'Backspace' && !box.value && i > 0) { boxes[i - 1].focus(); boxes[i - 1].value = ''; sync(); e.preventDefault(); }
        else if (e.key === 'ArrowLeft' && i > 0) { boxes[i - 1].focus(); e.preventDefault(); }
        else if (e.key === 'ArrowRight' && i < len - 1) { boxes[i + 1].focus(); e.preventDefault(); }
      });
      box.addEventListener('paste', function (e) {
        e.preventDefault();
        var t = ((e.clipboardData || window.clipboardData).getData('text') || '').replace(/\D/g, '').slice(0, len).split('');
        for (var j = 0; j < len; j++) boxes[j].value = t[j] || '';
        sync();
        boxes[Math.min(t.length, len - 1)].focus();
      });
    });
    var api = {
      length: len,
      el: wrap,
      focus: function () { boxes[0].focus(); },
      clear: function () { boxes.forEach(function (b) { b.value = ''; }); sync(); boxes[0].focus(); }
    };
    input._otp = api;
    return api;
  }

  // Inject banner + password eyes whenever the DOM is ready. portal.js is
  // loaded synchronously near the top of every portal page so this fires
  // once per navigation.
  function _onPortalReady() {
    _renderImpersonationBanner();
    _initPasswordEyes(document);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _onPortalReady);
  } else {
    _onPortalReady();
  }

  return {
    apiFetch, setToken, getToken, logout, requireAuth,
    formatMoney, formatDate, cognito,
    getImpersonation, endImpersonation,
    initPasswordEyes: _initPasswordEyes,
    initOtp: _initOtp,
  };
})();
