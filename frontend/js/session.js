/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL SESSION MANAGER

   Industry-standard online-banking session timeout: 10 minutes of
   inactivity with a 1-minute warning. Activity is any click,
   keypress, scroll, mousemove, or touch. The moment the customer
   interacts with the page, the idle clock resets.

   Cognito IdToken is silently refreshed in the background while
   the customer is active (via REFRESH_TOKEN_AUTH using the
   refresh token stored from MFA). This means the customer can use
   the portal continuously for as long as they want; only sustained
   inactivity logs them out.

   Loaded on every signed-in page. Self-contained — no dependency
   on portal.js (which lives only in S3).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var ACCESS_KEY = 'cif_access_token';
  var REFRESH_KEY = 'cif_refresh_token';
  var LOGIN_URL = '/start.html';
  var COGNITO_REGION = 'us-east-1';
  var COGNITO_CLIENT_ID = '1mddi61n19hftaldt9t3r622b';

  // Industry-standard banking timeouts (Chase, BofA, Wells Fargo,
  // Capital One, Citi all use ~10 min idle).
  var IDLE_TIMEOUT_MS = 10 * 60 * 1000;       // 10 min idle → logout
  var WARN_BEFORE_LOGOUT_MS = 1 * 60 * 1000;  //  1 min warning before logout
  var IDLE_CHECK_INTERVAL_MS = 5 * 1000;      // check idle state every 5s
  var TOKEN_REFRESH_THRESHOLD_MS = 5 * 60 * 1000; // refresh token when < 5 min remain

  // Dev override: set sessionStorage.cif_idle_timeout_test_ms to a
  // millisecond count and reload to use a shorter idle timeout for
  // testing (e.g. 30000 = 30s idle instead of 10 min).
  var TEST_OVERRIDE_KEY = 'cif_idle_timeout_test_ms';

  var _lastActivity = Date.now();
  var _idleCheckInterval = null;
  var _refreshing = false;
  var _modalEl = null;
  var _countdownInterval = null;

  function effectiveIdleTimeout() {
    var override = parseInt(sessionStorage.getItem(TEST_OVERRIDE_KEY) || '', 10);
    return (override > 0) ? override : IDLE_TIMEOUT_MS;
  }

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

  function tokenRemainingMs() {
    var t = sessionStorage.getItem(TOKEN_KEY);
    if (!t) return 0;
    var c = decodeJwt(t);
    if (!c || !c.exp) return 0;
    return Math.max(0, c.exp * 1000 - Date.now());
  }

  function idleMs() {
    return Date.now() - _lastActivity;
  }

  // ─────────────────────────────────────────
  // Refresh via Cognito InitiateAuth
  // ─────────────────────────────────────────
  function refreshIdToken() {
    var refresh = sessionStorage.getItem(REFRESH_KEY);
    if (!refresh) return Promise.reject(new Error('no_refresh_token'));
    if (_refreshing) return _refreshing;
    _refreshing = fetch('https://cognito-idp.' + COGNITO_REGION + '.amazonaws.com/', {
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
    }).then(function (token) {
      _refreshing = false;
      return token;
    }).catch(function (err) {
      _refreshing = false;
      throw err;
    });
    return _refreshing;
  }

  // ─────────────────────────────────────────
  // Forced logout
  // ─────────────────────────────────────────
  function forceLogout(reason) {
    if (_idleCheckInterval) clearInterval(_idleCheckInterval);
    _idleCheckInterval = null;
    closeModal();
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(ACCESS_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
    var url = LOGIN_URL;
    if (reason) url += '?reason=' + encodeURIComponent(reason);
    window.location.replace(url);
  }

  // ─────────────────────────────────────────
  // Activity tracking
  // ─────────────────────────────────────────
  function recordActivity() {
    // Ignore activity while warning modal is showing — the customer
    // must explicitly click "Stay signed in" to extend, otherwise
    // mouse-twitch would reset the timer right after the modal
    // appeared, defeating the point.
    if (_modalEl) return;
    _lastActivity = Date.now();
  }

  function startActivityTracking() {
    var events = ['click', 'keydown', 'scroll', 'mousemove', 'touchstart'];
    events.forEach(function (evt) {
      document.addEventListener(evt, recordActivity, { passive: true, capture: true });
    });
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
      +   '<p>For your security, we’ll sign you out due to inactivity.</p>'
      +   '<p class="cif-session-countdown" aria-live="polite">'
      +     'Sign-out in <strong id="cifSessionCountdown">1:00</strong>'
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
      stayBtn.textContent = 'Staying signed in…';

      // Reset the idle clock so the customer gets a fresh window.
      _lastActivity = Date.now();

      // If the Cognito token is about to expire (or already has),
      // refresh it. Otherwise just close the modal — the existing
      // token is still good and the idle timer is now reset.
      var promise = (tokenRemainingMs() < TOKEN_REFRESH_THRESHOLD_MS)
        ? refreshIdToken()
        : Promise.resolve();

      promise.then(function () {
        closeModal();
      }).catch(function () {
        forceLogout('session_expired');
      });
    });

    return overlay;
  }

  function showModal() {
    if (_modalEl) return;
    _modalEl = buildModal();
    document.body.appendChild(_modalEl);
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
      var idle = idleMs();
      var remaining = Math.max(0, effectiveIdleTimeout() - idle);
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
  // Idle check loop
  // ─────────────────────────────────────────
  function checkIdle() {
    var idle = idleMs();
    var timeout = effectiveIdleTimeout();

    // Logged out due to total inactivity.
    if (idle >= timeout) {
      forceLogout('session_expired');
      return;
    }

    // Show warning modal at idle - WARN_BEFORE_LOGOUT_MS.
    if (idle >= timeout - WARN_BEFORE_LOGOUT_MS && !_modalEl) {
      showModal();
      return;
    }

    // Silent background refresh: if customer is active and the
    // Cognito token is approaching its expiry, refresh now so a
    // long active session never gets booted by token-exp alone.
    if (!_modalEl
        && idle < timeout - WARN_BEFORE_LOGOUT_MS
        && tokenRemainingMs() < TOKEN_REFRESH_THRESHOLD_MS
        && tokenRemainingMs() > 0
        && !_refreshing) {
      refreshIdToken().catch(function () {
        // If refresh fails, force logout so the customer doesn't
        // discover the failure mid-action with a 401.
        forceLogout('session_expired');
      });
    }
  }

  // ─────────────────────────────────────────
  // Init
  // ─────────────────────────────────────────
  function init() {
    if (!sessionStorage.getItem(TOKEN_KEY)) return;  // not signed in
    // Impersonation sessions don't carry a refresh token and have
    // their own 15-min server-side expiry — let impersonation.js
    // manage the lifecycle. Skip idle-tracking + silent refresh
    // here so the operator's session isn't forced-logged-out
    // mid-impersonation.
    if (sessionStorage.getItem('cif_impersonation_active') === '1') {
      return;
    }
    // If the token is already expired on load, log out cleanly.
    if (tokenRemainingMs() <= 0) {
      forceLogout('session_expired');
      return;
    }
    _lastActivity = Date.now();
    startActivityTracking();
    _idleCheckInterval = setInterval(checkIdle, IDLE_CHECK_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Tiny API for debugging / external triggers.
  window.CIF_SESSION = {
    refreshNow: function () { return refreshIdToken(); },
    forceLogout: forceLogout,
    getIdleMs: idleMs,
    getTokenRemainingMs: tokenRemainingMs,
    bumpActivity: recordActivity,  // for programmatic resets
  };
})();
