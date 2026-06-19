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
    // Wire every sign-out control this page might render: the legacy header
    // button (#signOutBtn), and the new app-shell's sidebar button
    // (#signOutBtnSidebar). The mobile drawer button (#signOutBtnMobile) is
    // wired below where the drawer is set up. sidebar.js also wires these,
    // so the handlers are idempotent (same signOut()).
    ['signOutBtn', 'signOutBtnSidebar'].forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.addEventListener('click', signOut);
    });

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
            '<a href="/dashboard.html" class="mobile-menu-logo"><img src="/images/Get-Fast-Cash-Loans-Cash-in-Flash.png" alt="Cash in Flash" width="180" height="23"></a>' +
            '<button class="mobile-menu-close" id="mobile-menu-close" aria-label="Close menu"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18"/><path d="M6 6l12 12"/></svg></button>' +
          '</div>' +
          '<div class="mobile-menu-user">' +
            '<span class="mobile-menu-avatar" aria-hidden="true"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></span>' +
            '<div class="mobile-menu-user-text"><p>Welcome back,</p><strong class="dash-first-name">there</strong></div>' +
          '</div>' +
          '<nav class="mobile-menu-cards" aria-label="Account">' +
            '<a href="/dashboard.html" class="mobile-menu-card mobile-nav-link">' +
              '<span class="mobile-menu-card-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V10"/></svg></span>' +
              '<span class="mobile-menu-card-label">Home</span>' +
              '<svg class="mobile-menu-card-chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9aa4b2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
            '</a>' +
            '<a href="/loans.html" class="mobile-menu-card mobile-nav-link">' +
              '<span class="mobile-menu-card-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></span>' +
              '<span class="mobile-menu-card-label">My Loans</span>' +
              '<svg class="mobile-menu-card-chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9aa4b2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
            '</a>' +
            '<a href="/payments.html" class="mobile-menu-card mobile-nav-link">' +
              '<span class="mobile-menu-card-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M14.5 9.5a2.5 2 0 0 0-2.5-1.5c-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2a2.5 2 0 0 1-2.5-1.5M12 6.5v11"/></svg></span>' +
              '<span class="mobile-menu-card-label">Payments</span>' +
              '<svg class="mobile-menu-card-chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9aa4b2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
            '</a>' +
            '<a href="/profile.html" class="mobile-menu-card mobile-nav-link">' +
              '<span class="mobile-menu-card-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0E8741" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></span>' +
              '<span class="mobile-menu-card-label">Profile</span>' +
              '<svg class="mobile-menu-card-chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9aa4b2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
            '</a>' +
          '</nav>' +
          '<div class="mobile-menu-extra">' +
            '<button id="signOutBtnMobile" class="mobile-menu-signout" type="button"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>Sign Out</button>' +
          '</div>' +
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
      Array.prototype.forEach.call(m.querySelectorAll('.mobile-menu-card, .mobile-nav-item a'), function (a) {
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
