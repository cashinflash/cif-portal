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

  // Inject banner whenever the DOM is ready. portal.js is loaded
  // synchronously near the top of every portal page so this fires
  // once per navigation.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _renderImpersonationBanner);
  } else {
    _renderImpersonationBanner();
  }

  return {
    apiFetch, setToken, getToken, logout, requireAuth,
    formatMoney, formatDate, cognito,
    getImpersonation, endImpersonation,
  };
})();
