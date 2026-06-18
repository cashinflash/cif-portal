/* ═══════════════════════════════════════
   CASH IN FLASH — shared logic for every
   signed-in portal page (loans, documents,
   payments, request-loan).  Mirrors just the
   auth guard + handoff pieces of dashboard.js
   so we don't bloat the dashboard bundle.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/start.html';
  var token = sessionStorage.getItem(TOKEN_KEY);

  function decodeJwt(t) {
    try {
      var b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      b64 = b64 + '==='.slice((b64.length + 3) % 4);
      return JSON.parse(decodeURIComponent(atob(b64).split('').map(function (c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join('')));
    } catch (_) { return null; }
  }

  var claims = token ? decodeJwt(token) : null;
  var expired = !claims || (claims.exp && claims.exp * 1000 < Date.now() + 15 * 1000);
  if (!token || expired) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_URL);
    return;
  }

  document.addEventListener('DOMContentLoaded', function () {
    // User chip / greeting
    var first = (claims.given_name || '').trim();
    var chip = document.getElementById('userChip');
    if (chip) chip.textContent = first ? ('Hi, ' + first) : (claims.email || 'Account');

    var y = document.getElementById('footerYear');
    if (y) y.textContent = String(new Date().getFullYear());

    // Sign out
    function signOut() {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem('cif_access_token');
      sessionStorage.removeItem('cif_refresh_token');
      window.location.replace(LOGIN_URL);
    }
    var so = document.getElementById('signOutBtn');
    if (so) so.addEventListener('click', signOut);

    // Mobile menu — these pages ship the hamburger button but NOT a drawer,
    // so the toggle was a dead control on phones. Inject a consistent drawer
    // (same styled menu as the dashboard) when one is missing, then wire it.
    var t = document.getElementById('menu-toggle');
    var m = document.getElementById('mobile-menu');
    if (t && !m) {
      m = document.createElement('div');
      m.className = 'mobile-menu';
      m.id = 'mobile-menu';
      m.innerHTML =
        '<div class="mobile-menu-inner">' +
          '<div class="mobile-menu-header">' +
            '<a href="/dashboard.html" class="mobile-menu-logo"><img src="/images/white_logo_350.png" alt="Cash in Flash" width="140" height="26"></a>' +
            '<button class="mobile-menu-close" id="mobile-menu-close" aria-label="Close menu"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18"/><path d="M6 6l12 12"/></svg></button>' +
          '</div>' +
          '<ul class="mobile-nav-list">' +
            '<li class="mobile-nav-item"><a href="/dashboard.html">Dashboard</a></li>' +
            '<li class="mobile-nav-item"><a href="/loans.html">My Loans</a></li>' +
            '<li class="mobile-nav-item"><a href="/payments.html">Payments</a></li>' +
            '<li class="mobile-nav-item"><a href="/profile.html">Profile</a></li>' +
          '</ul>' +
          '<div class="mobile-menu-extra"><div class="mobile-btn-row">' +
            '<button id="signOutBtnMobile" class="btn-login" type="button">Sign out</button>' +
          '</div></div>' +
        '</div>';
      document.body.appendChild(m);
    }
    if (t && m) {
      var closeMenu = function () { m.classList.remove('open'); t.classList.remove('active'); };
      t.addEventListener('click', function () {
        m.classList.toggle('open');
        t.classList.toggle('active');
      });
      var mc = document.getElementById('mobile-menu-close');
      if (mc) mc.addEventListener('click', closeMenu);
      Array.prototype.forEach.call(m.querySelectorAll('.mobile-nav-item a'), function (a) {
        a.addEventListener('click', closeMenu);
      });
      var soM = document.getElementById('signOutBtnMobile');
      if (soM) soM.addEventListener('click', signOut);
    }

    // Vergent handoff for "Open Vergent portal" + "Request a new loan" buttons.
    var handoffButtons = document.querySelectorAll(
      '[data-action="open-vergent-portal"], [data-action="new-loan"]'
    );
    Array.prototype.forEach.call(handoffButtons, function (btn) {
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        var orig = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Starting…';
        fetch('/api/my-loan/new', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }
        }).then(function (r) { return r.json(); })
          .then(function (data) {
            if (data && data.url) {
              window.location.href = data.url;
              return;
            }
            btn.disabled = false;
            btn.textContent = orig;
            alert('Could not connect to the portal. Please try again or call (888) 999-9859.');
          })
          .catch(function () {
            btn.disabled = false;
            btn.textContent = orig;
            alert('Network error. Please try again.');
          });
      });
    });
  });
})();
