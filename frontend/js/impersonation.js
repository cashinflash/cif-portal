/* ═══════════════════════════════════════
   CASH IN FLASH — IMPERSONATION SUPPORT (admin)

   Loaded on every signed-in customer page. Does three things:

   1. Bootstrap from URL fragment. cif-dashboard's "View as
      customer" flow opens the portal with a fragment like:
        #impersonationToken=<T>&jwt=<J>&name=<N>&cid=<C>&exp=<unix>
      Pull those values out, save to sessionStorage, scrub the
      fragment so the token isn't in the URL bar. Must run on
      script parse (NOT DOMContentLoaded) so the JWT is in
      sessionStorage by the time dashboard.js / loans.js /
      session.js do their auth-guard checks.

   2. Inject X-Impersonation-Token on every same-origin fetch.
      Each per-page script (dashboard.js, loans.js, payments.js)
      makes its own raw fetch with just Authorization: Bearer.
      We monkey-patch window.fetch globally so the impersonation
      header rides along without touching each script.

   3. Render the read-only banner + handle "End now" click.
      Sticky red bar at the top of the page with the target
      customer name, ID, live countdown, and an End button.
      Auto-ends when the token expires.

   Self-contained — no dependency on portal.js (which only loads
   on signup/login pages).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var IMP_TOKEN_KEY = 'cif_impersonation_token';
  var IMP_META_KEY = 'cif_impersonation_meta';
  var IMP_ACTIVE_KEY = 'cif_impersonation_active';

  // ── 1. Bootstrap from URL fragment ──────────────────────
  try {
    var hash = window.location.hash || '';
    if (hash.indexOf('impersonationToken=') >= 0) {
      var raw = hash.charAt(0) === '#' ? hash.slice(1) : hash;
      var params = new URLSearchParams(raw);
      var impToken = params.get('impersonationToken');
      if (impToken) {
        sessionStorage.setItem(IMP_TOKEN_KEY, impToken);
        sessionStorage.setItem(IMP_META_KEY, JSON.stringify({
          name: params.get('name') || '',
          cid: params.get('cid') || '',
          email: params.get('email') || '',
          exp: parseInt(params.get('exp') || '0', 10) || 0,
        }));
        // Sentinel for session.js — when active, skip silent
        // JWT refresh (we don't have a refresh token).
        sessionStorage.setItem(IMP_ACTIVE_KEY, '1');
        var jwt = params.get('jwt') || '';
        if (jwt) sessionStorage.setItem(TOKEN_KEY, jwt);
        var clean = window.location.pathname + window.location.search;
        window.history.replaceState(null, '', clean);
      }
    }
  } catch (e) {
    console.warn('impersonation bootstrap failed', e);
  }

  function getInfo() {
    var t = sessionStorage.getItem(IMP_TOKEN_KEY);
    if (!t) return null;
    var meta = {};
    try {
      meta = JSON.parse(sessionStorage.getItem(IMP_META_KEY) || '{}');
    } catch (e) { /* ignore */ }
    return {
      token: t,
      name: meta.name || '',
      cid: meta.cid || '',
      email: meta.email || '',
      exp: meta.exp || 0,
    };
  }

  // ── 2. window.fetch wrap ──────────────────────────────
  if (!window.__cif_imp_fetch_patched) {
    window.__cif_imp_fetch_patched = true;
    var origFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      try {
        var info = getInfo();
        if (info) {
          init = init || {};
          var url = (typeof input === 'string')
            ? input
            : (input && input.url) || '';
          // Same-origin only — never leak the token to third
          // parties (Cognito refresh calls, Plaid, etc.).
          var sameOrigin = !url || url.charAt(0) === '/'
            || url.indexOf(window.location.origin) === 0;
          if (sameOrigin) {
            var headers = new Headers(init.headers
              || (input && input.headers) || {});
            headers.set('X-Impersonation-Token', info.token);
            init.headers = headers;
          }
        }
      } catch (e) {
        console.warn('impersonation fetch wrap failed', e);
      }
      return origFetch(input, init);
    };
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[<>&"]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c];
    });
  }

  function endImpersonation() {
    var info = getInfo();
    sessionStorage.removeItem(IMP_TOKEN_KEY);
    sessionStorage.removeItem(IMP_META_KEY);
    sessionStorage.removeItem(IMP_ACTIVE_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    if (info && info.token) {
      try {
        // Best-effort server-side revoke. fire-and-forget — we're
        // about to navigate away.
        fetch('/api/admin/end-impersonate', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Impersonation-Token': info.token,
          },
          body: JSON.stringify({ token: info.token }),
          keepalive: true,
        });
      } catch (e) { /* ignore */ }
    }
    try { window.close(); } catch (e) { /* ignore */ }
    window.location.href = 'about:blank';
  }

  // ── 3. Banner ─────────────────────────────────────────
  function renderBanner() {
    var info = getInfo();
    if (!info) return;
    if (document.getElementById('cif-impersonation-banner')) return;
    if (!document.body) return;

    var bar = document.createElement('div');
    bar.id = 'cif-impersonation-banner';
    bar.style.cssText = [
      'position:sticky', 'top:0', 'z-index:99999',
      'background:#5a0d0d', 'color:#fff',
      'font-family:inherit', 'font-size:13px', 'font-weight:600',
      'padding:10px 16px',
      'display:flex', 'align-items:center', 'gap:12px',
      'flex-wrap:wrap',
      'box-shadow:0 2px 6px rgba(0,0,0,.2)',
    ].join(';');

    var who = info.name || ('Customer #' + info.cid);
    var cidPart = info.cid ? ' · #' + info.cid : '';
    bar.innerHTML =
      '<div style="flex:1;min-width:200px">' +
        '⚠️ VIEWING AS CUSTOMER: <b>' + escapeHtml(who) + '</b>' +
        escapeHtml(cidPart) +
        ' <span style="opacity:.75;margin-left:6px">(read-only)</span>' +
      '</div>' +
      '<span id="cif-imp-expiry" style="font-size:11px;opacity:.85;font-weight:500"></span>' +
      '<button type="button" id="cif-imp-end" ' +
      'style="background:#fff;color:#5a0d0d;border:none;border-radius:6px;' +
      'padding:6px 14px;font-size:12px;font-weight:700;cursor:pointer;' +
      'font-family:inherit">End now</button>';

    document.body.insertBefore(bar, document.body.firstChild);
    var endBtn = document.getElementById('cif-imp-end');
    if (endBtn) endBtn.addEventListener('click', endImpersonation);

    // Hide write controls — best-effort UX. The customer
    // Lambdas also 403 writes server-side regardless.
    var style = document.createElement('style');
    style.textContent =
      '#cif-impersonation-banner ~ * form button[type="submit"]:not([data-allow-impersonation]),' +
      '#cif-impersonation-banner ~ * .btn-primary:not([data-allow-impersonation]),' +
      '#cif-impersonation-banner ~ * .btn-danger:not([data-allow-impersonation]) {' +
      '  opacity:.35 !important; pointer-events:none !important; cursor:not-allowed !important;' +
      '}';
    document.head.appendChild(style);

    function tick() {
      if (!info.exp) return;
      var remaining = Math.max(0, info.exp - Math.floor(Date.now() / 1000));
      var el = document.getElementById('cif-imp-expiry');
      if (!el) return;
      if (remaining === 0) { endImpersonation(); return; }
      var m = Math.floor(remaining / 60);
      var s = remaining % 60;
      el.textContent = 'expires in ' + m + ':' + (s < 10 ? '0' : '') + s;
    }
    tick();
    setInterval(tick, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderBanner);
  } else {
    renderBanner();
  }

  // Tiny public API.
  window.CIF_IMPERSONATION = {
    isActive: function () { return !!getInfo(); },
    info: getInfo,
    end: endImpersonation,
  };
})();
