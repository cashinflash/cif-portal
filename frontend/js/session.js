/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL SESSION MANAGER

   Token-expiry-based session timeout with a "stay signed in?"
   warning modal that fires 2 minutes before expiry. Refreshes
   Cognito IdToken via REFRESH_TOKEN_AUTH using the refresh token
   already stored from the MFA flow.

   Loaded on every signed-in page (dashboard, loans, payments,
   request-loan). Self-contained — no dependency on portal.js
   (which lives only in S3).

   Without this module: when the IdToken hits its expiry, the
   first 401 on any API call dumps the customer at /start.html
   with no explanation. With it: customer sees a warning + one-
   click "stay signed in" before that ever happens.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var ACCESS_KEY = 'cif_access_token';
  var REFRESH_KEY = 'cif_refresh_token';
  var LOGIN_URL = '/start.html';
  var WARN_BEFORE_MS = 2 * 60 * 1000;       // show modal 2 min before exp
  var COGNITO_REGION = 'us-east-1';
  var COGNITO_CLIENT_ID = '1mddi61n19hftaldt9t3r622b';

  // Dev override: set sessionStorage.cif_session_test_warn_in to a
  // millisecond count to force the warning to fire that many ms from
  // page load (regardless of actual token expiry). Useful for
  // verifying the modal without waiting an hour.
  var TEST_WARN_OVERRIDE_KEY = 'cif_session_test_warn_in';

  var _warnTimer = null;
  var _expireTimer = null;
  var _modalEl = null;
  var _countdownInterval = null;

  // ─────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────
  function decodeJwt(token) {
    try {
      var p = token.split('.')[1];
      var b = p.replace(/-/g, '+').replace(/_/g, '/');
      var pad = b + '==='.slice((b.length + 3) % 4);
      return JSON.parse(decodeURIComponent(
        atob(pad).split('').map(function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      ));
    } catch (e) { return null; }
  }

  function getExpMs() {
    var t = sessionStorage.getItem(TOKEN_KEY);
    if (!t) return 0;
    var c = decodeJwt(t);
    return (c && c.exp) ? c.exp * 1000 : 0;
  }

  function clearTimers() {
    if (_warnTimer) clearTimeout(_warnTimer);
    if (_expireTimer) clearTimeout(_expireTimer);
    _warnTimer = null;
    _expireTimer = null;
  }

  // ─────────────────────────────────────────
  // Refresh via Cognito InitiateAuth
  // ─────────────────────────────────────────
  function refreshIdToken() {
    var refresh = sessionStorage.getItem(REFRESH_KEY);
    if (!refresh) return Promise.reject(new Error('no_refresh_token'));
    return fetch('https://cognito-idp.' + COGNITO_REGION + '.amazonaws.com/', {
      method: 'POST',
      headers: {
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
        'Content-Type': 'application/x-amz-json-1.1',
      },
      body: JSON.stringify({
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        ClientId: COGNITO_CLIENT_ID,
        AuthParameters: { REFRESH_TOKEN: refresh },
      }),
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.message || data.__type || 'refresh_failed');
        var auth = data.AuthenticationResult || {};
        if (!auth.IdToken) throw new Error('refresh_no_id_token');
        sessionStorage.setItem(TOKEN_KEY, auth.IdToken);
        if (auth.AccessToken) sessionStorage.setItem(ACCESS_KEY, auth.AccessToken);
        // Cognito's REFRESH_TOKEN_AUTH does NOT return a new
        // RefreshToken; the old one keeps working until its own
        // expiry (default 30 days).
        return auth.IdToken;
      });
    });
  }

  // ─────────────────────────────────────────
  // Forced logout
  // ─────────────────────────────────────────
  function forceLogout(reason) {
    clearTimers();
    closeModal();
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(ACCESS_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
    var url = LOGIN_URL;
    if (reason) url += '?reason=' + encodeURIComponent(reason);
    window.location.replace(url);
  }

  // ─────────────────────────────────────────
  // Modal
  // ─────────────────────────────────────────
  function buildModal() {
    var overlay = document.createElement('div');
    overlay.className = 'cif-session-modal';
    overlay.setAttribute('role', 'alertdialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'cifSessionTitle');
    overlay.innerHTML = ''
      + '<div class="cif-session-modal-backdrop" aria-hidden="true"></div>'
      + '<div class="cif-session-modal-card">'
      +   '<h3 id="cifSessionTitle">Stay signed in?</h3>'
      +   '<p>For your security, we’ll sign you out soon due to inactivity.</p>'
      +   '<p class="cif-session-countdown" aria-live="polite">'
      +     'Sign-out in <strong id="cifSessionCountdown">2:00</strong>'
      +   '</p>'
      +   '<div class="cif-session-actions">'
      +     '<button type="button" class="btn-login" id="cifSessionLogout">Sign out</button>'
      +     '<button type="button" class="btn-apply" id="cifSessionStay">Stay signed in</button>'
      +   '</div>'
      + '</div>';

    var stayBtn = overlay.querySelector('#cifSessionStay');
    var logoutBtn = overlay.querySelector('#cifSessionLogout');

    logoutBtn.addEventListener('click', function () {
      forceLogout('signed_out');
    });

    stayBtn.addEventListener('click', function () {
      stayBtn.disabled = true;
      logoutBtn.disabled = true;
      stayBtn.textContent = 'Refreshing…';
      refreshIdToken().then(function () {
        closeModal();
        scheduleTimers();
      }).catch(function () {
        // Refresh failed (token expired, network, etc.) — fall back
        // to a hard logout. Customer sees session_expired banner on
        // /start.html and signs in fresh.
        forceLogout('session_expired');
      });
    });

    return overlay;
  }

  function showModal() {
    if (_modalEl) return;
    _modalEl = buildModal();
    document.body.appendChild(_modalEl);
    // Auto-focus the primary action so keyboard users land on it.
    var stay = _modalEl.querySelector('#cifSessionStay');
    if (stay) {
      try { stay.focus(); } catch (e) { /* ignore */ }
    }
    startCountdown();
  }

  function closeModal() {
    if (_countdownInterval) {
      clearInterval(_countdownInterval);
      _countdownInterval = null;
    }
    if (_modalEl && _modalEl.parentNode) {
      _modalEl.parentNode.removeChild(_modalEl);
    }
    _modalEl = null;
  }

  function startCountdown() {
    function tick() {
      var exp = getExpMs();
      var remaining = Math.max(0, exp - Date.now());
      var el = _modalEl && _modalEl.querySelector('#cifSessionCountdown');
      if (el) {
        var m = Math.floor(remaining / 60000);
        var s = Math.floor((remaining % 60000) / 1000);
        el.textContent = m + ':' + (s < 10 ? '0' : '') + s;
      }
      if (remaining <= 0) forceLogout('session_expired');
    }
    tick();
    _countdownInterval = setInterval(tick, 1000);
  }

  // ─────────────────────────────────────────
  // Scheduling
  // ─────────────────────────────────────────
  function scheduleTimers() {
    clearTimers();
    var exp = getExpMs();
    if (!exp) return;
    var now = Date.now();

    // Dev override for testing: force the warning to fire N ms from
    // page load instead of from token exp. Stored in sessionStorage
    // so it survives a reload but not a sign-out/sign-in.
    var override = parseInt(sessionStorage.getItem(TEST_WARN_OVERRIDE_KEY) || '', 10);
    var warnAt;
    if (override > 0) {
      warnAt = now + override;
    } else {
      warnAt = exp - WARN_BEFORE_MS;
    }

    // If we're already past the warning point but not yet expired,
    // show immediately. If already expired, log out immediately.
    if (exp <= now) {
      forceLogout('session_expired');
      return;
    }
    if (warnAt <= now) {
      showModal();
    } else {
      _warnTimer = setTimeout(showModal, warnAt - now);
    }
    _expireTimer = setTimeout(function () {
      forceLogout('session_expired');
    }, exp - now);
  }

  // ─────────────────────────────────────────
  // Init
  // ─────────────────────────────────────────
  function init() {
    if (!sessionStorage.getItem(TOKEN_KEY)) return;  // not signed in
    scheduleTimers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose a tiny API for other modules to nudge us (e.g. when a
  // page-specific api() helper sees a successful 200, reset timers
  // in case the response carried a new token — currently it doesn't,
  // but the hook is here).
  window.CIF_SESSION = {
    refreshNow: function () { return refreshIdToken().then(scheduleTimers); },
    rescheduleTimers: scheduleTimers,
    forceLogout: forceLogout,
  };
})();
