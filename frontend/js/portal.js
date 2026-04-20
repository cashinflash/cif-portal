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

  async function apiFetch(path, opts = {}) {
    const token = sessionStorage.getItem('cif_id_token') || '';
    const headers = Object.assign(
      { 'Content-Type': 'application/json' },
      opts.headers || {}
    );
    if (token) headers.Authorization = `Bearer ${token}`;

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

  return { apiFetch, setToken, getToken, logout, requireAuth, formatMoney, formatDate, cognito };
})();
