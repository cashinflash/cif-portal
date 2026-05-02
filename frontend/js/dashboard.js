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

  function formatCurrencyPrecise(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toLocaleString('en-US', {
      style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function formatApr(n) {
    if (n === null || n === undefined || isNaN(Number(n))) return '—';
    return Number(n).toFixed(2) + '% APR';
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
        window.location.replace(LOGIN_URL + '?reason=session_expired');
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
    window.location.replace(LOGIN_URL + '?reason=session_expired');
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
    const sidebarName = qs('#sidebarUserName');
    if (sidebarName) {
      sidebarName.textContent = firstName
        ? ('Hi, ' + firstName)
        : (claims.email || 'Account');
    }
    const yearEl = qs('#footerYear');
    if (yearEl) yearEl.textContent = String(new Date().getFullYear());

    wireSignOut();
    wireMobileMenu();
    wireNewLoanButton();
    showPaymentSuccessBanner();  // one-shot "payment posted" banner
    renderProfileFromClaims();   // instant render from JWT claims
    loadProfileFromApi();         // hydrate with Vergent data (account status, phone hint, text-messaging flag)
    loadActiveLoan();
  });

  // ---------- One-shot "payment received" banner ----------
  function showPaymentSuccessBanner() {
    const raw = sessionStorage.getItem('cif_payment_success');
    if (!raw) return;
    sessionStorage.removeItem('cif_payment_success');
    let info;
    try { info = JSON.parse(raw); } catch (e) { return; }
    if (!info) return;
    const amount = Number(info.amount || 0).toLocaleString('en-US', {
      style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
    const banner = document.createElement('div');
    banner.className = 'dash-banner dash-banner--ok';
    banner.innerHTML = (
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>' +
      '<span>Payment of <strong>' + amount + '</strong> received. Your loan has been updated.</span>' +
      '<button type="button" class="dash-banner-close" aria-label="Dismiss">&times;</button>'
    );
    const main = qs('.dash-main');
    const hero = qs('.dash-hero');
    if (main && hero && main.parentNode) {
      main.parentNode.insertBefore(banner, main);
    } else if (hero && hero.parentNode) {
      hero.parentNode.insertBefore(banner, hero.nextSibling);
    }
    const close = qs('.dash-banner-close', banner);
    if (close) close.addEventListener('click', function () { banner.remove(); });
  }

  // ---------- Profile card ----------
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
  }

  function loadProfileFromApi() {
    api('/api/my-profile', token)
      .then(function (data) {
        if (!data) return;

        // Phone hint from Vergent (e.g. "•••-•••-8388"). Only show if Cognito has no phone.
        if (!claims.phone_number && data.vergentPhoneHint) {
          setText(qs('#profilePhone'), data.vergentPhoneHint);
          const row = qs('#profilePhoneRow');
          if (row) row.hidden = false;
        }

        // Vergent is the source of truth for email. If Vergent has
        // an email on file, show that one (the Cognito sign-in email
        // gets re-synced separately when an admin updates Vergent).
        if (data.vergentEmail) {
          const emailEl = qs('#profileEmail');
          if (emailEl) emailEl.textContent = data.vergentEmail;
        }

        // Account status pill — e.g. "Good". Never surface storeName:
        // that's Vergent's internal store directory and customers
        // shouldn't see it.
        const src = qs('#profileSource');
        if (src && data.statusName) {
          src.textContent = 'Account: ' + data.statusName;
          src.hidden = false;
          src.classList.remove('dash-profile-source--bad');
          if ((data.statusName || '').toLowerCase() !== 'good') {
            src.classList.add('dash-profile-source--bad');
          }
        }

        // "Set up security questions" nudge
        const hint = qs('#profileHint');
        if (hint && data.isSecurityQuestionsSetup === false) {
          hint.innerHTML = 'Security questions not set. <a href="/forgot.html">Set them up</a> for easier password recovery.';
        } else if (hint) {
          hint.textContent = 'Need to change your name, phone, or address? Call us at (818) 800-5227.';
        }
      })
      .catch(function () { /* non-critical — profile already has Cognito data */ });
  }

  // ---------- Request a new loan: hand off to Vergent apply portal ----------
  function wireNewLoanButton() {
    // Convert any <a href="/request-loan.html"> into handoff triggers.
    qsa('a[href="/request-loan.html"], a[href="/request-loan.html#new"], [data-action="new-loan"]').forEach(function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        const orig = a.textContent;
        a.style.pointerEvents = 'none';
        a.textContent = 'Starting…';
        fetch('/api/my-loan/new', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }
        }).then(function (r) { return r.json(); })
          .then(function (data) {
            if (data && data.url) {
              window.location.href = data.url;
              return;
            }
            a.textContent = orig;
            a.style.pointerEvents = '';
            alert('Could not start a new loan request. Please try again or call (818) 800-5227.');
          })
          .catch(function () {
            a.textContent = orig;
            a.style.pointerEvents = '';
            alert('Network error. Please try again.');
          });
      });
    });
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
      .then(function (data) {
        renderActiveLoan(card, data);
        renderLoanList(qs('#loanListBody'), (data && data.allLoans) || []);
        renderMemberSince((data && data.allLoans) || []);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderActiveLoan(card, null);
        renderLoanList(qs('#loanListBody'), []);
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

    setText(qs('[data-loan-balance]', card), formatCurrencyPrecise(loan.balance).replace(/^\$/, ''));
    setText(qs('[data-loan-principal]', card), formatCurrencyPrecise(loan.principal));
    setText(qs('[data-loan-next-due]', card), formatDate(loan.nextDueDate));
    setText(qs('[data-loan-next-amount]', card), formatCurrencyPrecise(loan.nextDueAmount));
    setText(qs('[data-loan-fee]', card), formatCurrencyPrecise(loan.fees));

    // Public loan id tag next to the "Active loan" heading.
    const idTag = qs('[data-loan-public-id]', card);
    if (idTag) {
      const pid = loan.publicId || loan.id;
      if (pid) {
        idTag.textContent = 'Loan #' + pid;
        idTag.hidden = false;
      } else {
        idTag.hidden = true;
      }
    }

    const autopayPill = qs('[data-loan-autopay]', card);
    if (autopayPill) autopayPill.hidden = !loan.autopay;

    renderProgress(card, loan);
    renderCountdown(card, loan);

    const captionEl = qs('[data-loan-caption]', card);
    if (captionEl) {
      if (loan.nextDueDate && loan.nextDueAmount) {
        captionEl.textContent = 'Next payment of ' + formatCurrencyPrecise(loan.nextDueAmount) +
                                ' is due ' + formatDate(loan.nextDueDate) + '.';
      } else {
        captionEl.textContent = 'Current balance remaining on your loan.';
      }
    }

    const pill = qs('[data-loan-status]', card);
    if (pill) {
      const status = (loan.status || '').toLowerCase();
      const daysLate = (loan.daysLate || '').toLowerCase();
      pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due');
      if (status.indexOf('past') !== -1 || status.indexOf('delinquent') !== -1 || (daysLate && daysLate !== 'not late')) {
        pill.classList.add('dash-pill--past-due');
        pill.textContent = 'Past due';
      } else if (status.indexOf('grace') !== -1 || status.indexOf('pending') !== -1 || loan.isInRescindPeriod) {
        pill.classList.add('dash-pill--warn');
        pill.textContent = loan.isInRescindPeriod ? 'Rescind period' : loan.status;
      } else {
        pill.classList.add('dash-pill--ok');
        pill.textContent = loan.status || 'Current';
      }
    }
  }

  function renderProgress(card, loan) {
    const wrap = qs('[data-loan-progress]', card);
    if (!wrap) return;
    const principal = Number(loan.principal);
    const fees = Number(loan.fees || 0);
    const balance = Number(loan.balance);
    const total = principal + fees;
    if (!isFinite(principal) || !isFinite(balance) || total <= 0) {
      wrap.hidden = true;
      return;
    }
    const paid = Math.max(0, total - balance);
    const remaining = Math.max(0, balance);
    const pct = Math.max(0, Math.min(100, (paid / total) * 100));
    const fill = qs('[data-loan-progress-fill]', wrap);
    if (fill) fill.style.width = pct.toFixed(1) + '%';
    setText(qs('[data-loan-paid]', wrap), formatCurrencyPrecise(paid));
    setText(qs('[data-loan-remaining]', wrap), formatCurrencyPrecise(remaining));
    wrap.hidden = false;
  }

  function renderCountdown(card, loan) {
    const el = qs('[data-loan-countdown]', card);
    if (!el) return;
    el.classList.remove('is-soon', 'is-late');
    if (!loan.nextDueDate) { el.hidden = true; return; }
    const due = new Date(loan.nextDueDate);
    if (isNaN(due.getTime())) { el.hidden = true; return; }
    // Compare dates at day-granularity — ignore clock time so "today" stays "today" all day.
    const today = new Date();
    const a = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
    const b = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    const days = Math.round((a - b) / 86400000);
    let text;
    if (days < 0) {
      text = Math.abs(days) + (Math.abs(days) === 1 ? ' day' : ' days') + ' past due';
      el.classList.add('is-late');
    } else if (days === 0) {
      text = 'Due today';
      el.classList.add('is-soon');
    } else if (days === 1) {
      text = 'Due tomorrow';
      el.classList.add('is-soon');
    } else {
      text = 'Due in ' + days + ' days';
      if (days <= 3) el.classList.add('is-soon');
    }
    el.textContent = text;
    el.hidden = false;
  }

  // ---------- My loans list ----------
  function renderLoanList(root, loans) {
    if (!root) return;
    root.innerHTML = '';
    if (!loans || !loans.length) {
      const p = document.createElement('p');
      p.className = 'dash-loanlist-empty';
      p.textContent = 'No loans yet.';
      root.appendChild(p);
      return;
    }

    // Newest first, by loanDate / originationDate.
    const sorted = loans.slice().sort(function (a, b) {
      const da = new Date(a.loanDate || a.originationDate || 0).getTime();
      const db = new Date(b.loanDate || b.originationDate || 0).getTime();
      return db - da;
    });

    sorted.forEach(function (loan) {
      const row = document.createElement('div');
      row.className = 'dash-loanlist-row';

      const main = document.createElement('div');
      main.className = 'dash-loanlist-main';

      const top = document.createElement('div');
      top.className = 'dash-loanlist-top';

      const idEl = document.createElement('strong');
      idEl.textContent = 'Loan #' + (loan.publicId || loan.id || '—');
      top.appendChild(idEl);

      const pill = document.createElement('span');
      pill.className = 'dash-pill ' + (loan.isOutstanding ? 'dash-pill--ok' : 'dash-pill--closed');
      pill.textContent = loan.isOutstanding ? (loan.status || 'Current') : (loan.status || 'Closed');
      top.appendChild(pill);

      const small = document.createElement('small');
      const dateStr = loan.loanDate || loan.originationDate;
      small.textContent = 'Originated ' + (dateStr ? formatDate(dateStr) : '—');

      main.appendChild(top);
      main.appendChild(small);

      const right = document.createElement('div');
      right.className = 'dash-loanlist-amount';
      const label = document.createElement('small');
      label.textContent = loan.isOutstanding ? 'Balance' : 'Borrowed';
      const amt = document.createElement('strong');
      amt.textContent = formatCurrencyPrecise(loan.isOutstanding ? loan.balance : loan.principal);
      right.appendChild(label);
      right.appendChild(amt);

      row.appendChild(main);
      row.appendChild(right);
      root.appendChild(row);
    });
  }

  // ---------- Member since (earliest loan year) ----------
  function renderMemberSince(loans) {
    const row = qs('#profileMemberSinceRow');
    const val = qs('#profileMemberSince');
    if (!row || !val || !loans || !loans.length) return;
    let earliest = null;
    loans.forEach(function (loan) {
      const d = new Date(loan.loanDate || loan.originationDate || 0);
      if (!isNaN(d.getTime()) && d.getTime() > 0 && (!earliest || d < earliest)) {
        earliest = d;
      }
    });
    if (!earliest) return;
    val.textContent = String(earliest.getFullYear());
    row.hidden = false;
  }

  // ---------- Sign out ----------
  function wireSignOut() {
    function signOut() {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem('cif_access_token');
      sessionStorage.removeItem('cif_refresh_token');
      window.location.replace(LOGIN_URL + '?reason=session_expired');
    }
    const btn = qs('#signOutBtn');
    const btnMobile = qs('#signOutBtnMobile');
    const btnSidebar = qs('#signOutBtnSidebar');
    if (btn) btn.addEventListener('click', signOut);
    if (btnMobile) btnMobile.addEventListener('click', signOut);
    if (btnSidebar) btnSidebar.addEventListener('click', signOut);
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
