/* ═══════════════════════════════════════
   CASH IN FLASH — Shared portal sidebar wiring.
   Runs on every signed-in portal page. Populates the user's name,
   wires the sign-out button, and marks the current nav link.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/start.html';

  function decodeJwt(token) {
    try {
      var payload = token.split('.')[1];
      var b64 = payload.replace(/-/g, '+').replace(/_/g, '/');
      var padded = b64 + '==='.slice((b64.length + 3) % 4);
      return JSON.parse(decodeURIComponent(
        atob(padded).split('').map(function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      ));
    } catch (e) { return null; }
  }

  function signOut() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem('cif_access_token');
    sessionStorage.removeItem('cif_refresh_token');
    window.location.replace(LOGIN_URL);
  }

  function init() {
    var token = sessionStorage.getItem(TOKEN_KEY);
    var claims = token ? decodeJwt(token) : null;

    // User name (sidebar + any existing #userChip)
    var first = (claims && (claims.given_name || '')).trim ? claims.given_name || '' : '';
    var label = first ? ('Hi, ' + first) : (claims && claims.email) || 'Account';
    var nameEl = document.getElementById('sidebarUserName');
    if (nameEl) nameEl.textContent = label;
    var chip = document.getElementById('userChip');
    if (chip) chip.textContent = label;

    // Sign-out wiring for any sign-out button on the page.
    var ids = ['signOutBtn', 'signOutBtnMobile', 'signOutBtnSidebar'];
    ids.forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.addEventListener('click', signOut);
    });

    // Mark the active sidebar link based on the current pathname.
    var path = (window.location.pathname || '').replace(/\/$/, '');
    var links = document.querySelectorAll('.dash-sidebar-link');
    for (var i = 0; i < links.length; i++) {
      var href = (links[i].getAttribute('href') || '').replace(/\/$/, '');
      links[i].classList.toggle('is-active', href === path);
    }

    // Footer year
    var year = document.getElementById('footerYear');
    if (year) year.textContent = String(new Date().getFullYear());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
