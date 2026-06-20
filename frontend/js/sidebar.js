/* ═══════════════════════════════════════
   CASH IN FLASH — Shared portal sidebar wiring.
   Runs on every signed-in portal page. Populates the user's name,
   wires the sign-out button, and marks the current nav link.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/login.html';

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
    window.location.replace(LOGIN_URL + '?reason=signed_out');
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
    // Redesigned mobile drawer shows the bare first name after "Welcome back,".
    document.querySelectorAll('.dash-first-name').forEach(function (el) {
      el.textContent = first || 'there';
    });

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

    // Hide "Request a new loan" sidebar link if the customer already
    // has an active loan (per CA law, customers can't carry two
    // concurrent payday loans). Reads sessionStorage cache first to
    // avoid duplicate API calls on pages that already fetch loan
    // data; otherwise hits /api/my-loans/active itself.
    if (token) toggleNewLoanLink(token);

    // Footer year
    var year = document.getElementById('footerYear');
    if (year) year.textContent = String(new Date().getFullYear());
  }

  function setNewLoanLinkVisibility(hasActive) {
    // Toggle the <html> class first so the CSS rule kicks in
    // synchronously (matches the inline preflight script on each
    // page's <head>).
    document.documentElement.classList.toggle('cif-has-active-loan', !!hasActive);
    var newLoanLinks = document.querySelectorAll('.dash-sidebar-link[href="/request-loan.html"]');
    for (var i = 0; i < newLoanLinks.length; i++) {
      newLoanLinks[i].style.display = hasActive ? 'none' : '';
    }
  }

  function toggleNewLoanLink(token) {
    // Cache valid for 60s so we don't hammer the API on rapid nav.
    var cached = sessionStorage.getItem('cif_has_active_loan');
    var cachedAt = parseInt(sessionStorage.getItem('cif_has_active_loan_at') || '0', 10);
    var now = Date.now();
    if (cached !== null && (now - cachedAt) < 60000) {
      setNewLoanLinkVisibility(cached === 'true');
      return;
    }
    fetch('/api/my-loans/active', {
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
      },
      credentials: 'omit',
    }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    }).then(function (data) {
      var hasActive = !!(data && data.loan);
      sessionStorage.setItem('cif_has_active_loan', String(hasActive));
      sessionStorage.setItem('cif_has_active_loan_at', String(Date.now()));
      setNewLoanLinkVisibility(hasActive);
    }).catch(function () { /* silent — leave link as-is on network error */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
