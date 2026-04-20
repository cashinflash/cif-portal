/* ═══════════════════════════════════════
   CASH IN FLASH — CUSTOMER PORTAL DASHBOARD
   Client-side controller.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  // ---------- Config ----------
  const API_BASE = '/api';
  const TOKEN_KEY = 'cif_id_token';
  const ACTIVE_ENDPOINT = API_BASE + '/my-loans/active';
  const ACTIVITY_ENDPOINT = API_BASE + '/my-loans/activity?limit=5';
  const LOGIN_URL = '/start.html';

  // ---------- Helpers ----------
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function decodeJwt(token) {
    try {
      const payload = token.split('.')[1];
      const b64 = payload.replace(/-/g, '+').replace(/_/g, '/');
      const padded = b64 + '==='.slice((b64.length + 3) % 4);
      return JSON.parse(decodeURIComponent(
        atob(padded).split('').map(function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      ));
    } catch (e) {
      return null;
    }
  }

  function isExpired(claims) {
    if (!claims || !claims.exp) return true;
    return claims.exp * 1000 < Date.now() + 15 * 1000; // 15s skew
  }

  function formatCurrency(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
      style: 'currency', currency: 'USD', maximumFractionDigits: 0
    });
  }

  function formatCurrencyPrecise(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
      style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function setText(el, value) {
    if (!el) return;
    el.textContent = value;
  }

  function api(path, token) {
    return fetch(path, {
      method: 'GET',
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      credentials: 'omit'
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL);
        throw new Error('unauthorized');
      }
      if (!res.ok) {
        return res.text().then(function (txt) {
          const err = new Error('http ' + res.status);
          err.body = txt;
          throw err;
        });
      }
      return res.json();
    });
  }

  // ---------- Auth guard ----------
  const token = sessionStorage.getItem(TOKEN_KEY);
  const claims = token ? decodeJwt(token) : null;
  if (!token || !claims || isExpired(claims)) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.replace(LOGIN_URL);
    return;
  }

  // ---------- Greeting ----------
  document.addEventListener('DOMContentLoaded', function () {
    const firstName = claims.given_name || '';
    const welcome = qs('#welcomeHeading');
    if (welcome) {
      welcome.textContent = firstName ? ('Welcome back, ' + firstName + '.') : 'Welcome back.';
    }
    const chip = qs('#userChip');
    if (chip) {
      chip.textContent = firstName ? ('Hi, ' + firstName) : (claims.email || 'Account');
    }
    const yearEl = qs('#footerYear');
    if (yearEl) yearEl.textContent = String(new Date().getFullYear());

    wireSignOut();
    wireMobileMenu();
    renderProfileFromClaims();
    loadActiveLoan();
    loadActivity();
  });

  // ---------- Profile card (Cognito-only for now; Vergent layer added once /Customer/Profile unblocks) ----------
  function renderProfileFromClaims() {
    const root = document.querySelector('.dash-profile');
    if (!root) return;

    const first = (claims.given_name || '').trim();
    const last = (claims.family_name || '').trim();
    const full = (first + ' ' + last).trim() || claims.email || 'Cash in Flash customer';
    setText(qs('#profileName'), full);

    const initials = (
      (first.charAt(0) || '') +
      (last.charAt(0) || (claims.email || 'C').charAt(0))
    ).toUpperCase().slice(0, 2);
    setText(qs('#profileInitials'), initials || 'CF');

    setText(qs('#profileEmail'), claims.email || '—');
    if (claims.email_verified === true || claims.email_verified === 'true') {
      const badge = qs('#profileEmailVerified');
      if (badge) badge.hidden = false;
    }

    const phone = claims.phone_number || '';
    if (phone) {
      setText(qs('#profilePhone'), formatPhone(phone));
      const row = qs('#profilePhoneRow');
      if (row) row.hidden = false;
    }

    if (claims.auth_time) {
      // auth_time is the current sign-in time, not signup. Leave hidden until /Customer/Profile gives us createdDate.
      // Kept here so the row appears the moment Vergent data arrives.
    }
  }

  function formatPhone(raw) {
    const digits = String(raw).replace(/\D/g, '');
    if (digits.length === 11 && digits[0] === '1') {
      return '(' + digits.slice(1, 4) + ') ' + digits.slice(4, 7) + '-' + digits.slice(7);
    }
    if (digits.length === 10) {
      return '(' + digits.slice(0, 3) + ') ' + digits.slice(3, 6) + '-' + digits.slice(6);
    }
    return raw;
  }

  // ---------- Active loan ----------
  function loadActiveLoan() {
    const card = qs('#activeLoanCard');
    if (!card) return;

    api(ACTIVE_ENDPOINT, token)
      .then(function (data) { renderActiveLoan(card, data); })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderActiveLoan(card, null);
      });
  }

  function renderActiveLoan(card, data) {
    card.setAttribute('aria-busy', 'false');
    const skeleton = qs('.dash-card-skeleton', card);
    const body = qs('.dash-loan-body', card);
    const empty = qs('.dash-loan-empty', card);
    if (skeleton) skeleton.style.display = 'none';

    if (!data || !data.loan) {
      if (body) body.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    const loan = data.loan;
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;

    setText(qs('[data-loan-balance]', card), formatCurrency(loan.balance).replace(/^\$/, ''));
    setText(qs('[data-loan-principal]', card), formatCurrencyPrecise(loan.principal));
    setText(qs('[data-loan-next-due]', card), formatDate(loan.nextDueDate));
    setText(qs('[data-loan-next-amount]', card), formatCurrencyPrecise(loan.nextDueAmount));

    const captionEl = qs('[data-loan-caption]', card);
    if (captionEl) {
      if (loan.nextDueDate && loan.nextDueAmount) {
        captionEl.textContent = 'Balance remaining. Next payment of ' +
          formatCurrencyPrecise(loan.nextDueAmount) + ' is due ' + formatDate(loan.nextDueDate) + '.';
      } else {
        captionEl.textContent = 'Current balance remaining on your loan.';
      }
    }

    const pill = qs('[data-loan-status]', card);
    if (pill) {
      const status = (loan.status || '').toLowerCase();
      pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due');
      if (status.indexOf('past') !== -1 || status.indexOf('delinquent') !== -1) {
        pill.classList.add('dash-pill--past-due');
        pill.textContent = 'Past due';
      } else if (status.indexOf('grace') !== -1 || status.indexOf('pending') !== -1) {
        pill.classList.add('dash-pill--warn');
        pill.textContent = loan.status;
      } else {
        pill.classList.add('dash-pill--ok');
        pill.textContent = loan.status || 'Current';
      }
    }
  }

  // ---------- Activity ----------
  function loadActivity() {
    const body = qs('#activityBody');
    if (!body) return;

    api(ACTIVITY_ENDPOINT, token)
      .then(function (data) { renderActivity(body, (data && data.items) || []); })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderActivity(body, []);
      });
  }

  function renderActivity(root, items) {
    root.innerHTML = '';
    if (!items.length) {
      const p = document.createElement('p');
      p.className = 'dash-activity-empty';
      p.textContent = 'No activity yet — your payments and charges will appear here.';
      root.appendChild(p);
      return;
    }
    items.forEach(function (it) {
      const row = document.createElement('div');
      row.className = 'dash-activity-row';

      const isDebit = Number(it.amount) > 0 && (it.direction === 'debit' || it.kind === 'charge');
      const iconWrap = document.createElement('div');
      iconWrap.className = 'dash-activity-icon' + (isDebit ? ' dash-activity-icon--out' : '');
      iconWrap.innerHTML = isDebit
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';

      const main = document.createElement('div');
      main.className = 'dash-activity-main';
      const strong = document.createElement('strong');
      strong.textContent = it.description || it.label || (isDebit ? 'Charge' : 'Payment');
      const small = document.createElement('small');
      small.textContent = formatDate(it.date);
      main.appendChild(strong);
      main.appendChild(small);

      const amt = document.createElement('div');
      amt.className = 'dash-activity-amount ' + (isDebit ? 'is-debit' : 'is-credit');
      const sign = isDebit ? '+' : '−'; // debit adds to balance, credit (payment) reduces balance
      amt.textContent = sign + formatCurrencyPrecise(Math.abs(Number(it.amount || 0)));

      row.appendChild(iconWrap);
      row.appendChild(main);
      row.appendChild(amt);
      root.appendChild(row);
    });
  }

  // ---------- Sign out ----------
  function wireSignOut() {
    function signOut() {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem('cif_access_token');
      sessionStorage.removeItem('cif_refresh_token');
      window.location.replace(LOGIN_URL);
    }
    const btn = qs('#signOutBtn');
    const btnMobile = qs('#signOutBtnMobile');
    if (btn) btn.addEventListener('click', signOut);
    if (btnMobile) btnMobile.addEventListener('click', signOut);
  }

  // ---------- Mobile menu ----------
  function wireMobileMenu() {
    const toggle = qs('#menu-toggle');
    const menu = qs('#mobile-menu');
    const close = qs('#mobile-menu-close');
    const overlay = qs('#mobile-overlay');
    if (!toggle || !menu) return;

    function open() {
      menu.classList.add('open');
      toggle.classList.add('active');
      document.body.style.overflow = 'hidden';
    }
    function shut() {
      menu.classList.remove('open');
      toggle.classList.remove('active');
      document.body.style.overflow = '';
    }

    toggle.addEventListener('click', function () {
      menu.classList.contains('open') ? shut() : open();
    });
    if (close) close.addEventListener('click', shut);
    if (overlay) overlay.addEventListener('click', shut);
    qsa('.mobile-nav-item a', menu).forEach(function (a) {
      a.addEventListener('click', shut);
    });
    window.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && menu.classList.contains('open')) shut();
    });
  }

  // Header shadow on scroll
  const header = qs('#site-header');
  if (header) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 4) header.classList.add('scrolled');
      else header.classList.remove('scrolled');
    }, { passive: true });
  }
})();
