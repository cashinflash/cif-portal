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

    // Brigit-style greeting header: "Monday, May 4 / Hey, Harut 👋"
    const dateEl = qs('#dashDate');
    if (dateEl) {
      try {
        dateEl.textContent = new Date().toLocaleDateString('en-US', {
          weekday: 'long', month: 'long', day: 'numeric',
        });
      } catch (e) {
        dateEl.textContent = '';
      }
    }
    const firstNameEl = qs('#dashFirstName');
    if (firstNameEl) firstNameEl.textContent = firstName || 'there';

    // Avatar initials (top right of greeting + sidebar fallback)
    const last = (claims.family_name || '').trim();
    const fallbackChar = (claims.email || 'C').charAt(0);
    const initials = (
      (firstName.charAt(0) || '') + (last.charAt(0) || fallbackChar)
    ).toUpperCase().slice(0, 2) || 'CF';
    const avatarEl = qs('#dashAvatarInitials');
    if (avatarEl) avatarEl.textContent = initials;

    // Legacy chip / sidebar name (still on mobile + sidebar bottom)
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
    renderProfileFromClaims();   // instant render from JWT claims (legacy selectors safe to call when missing)
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

        // Show the "set up security questions" nudge if applicable;
        // otherwise leave the default hint copy in place (which now
        // describes what the Manage profile link does).
        const hint = qs('#profileHint');
        if (hint && data.isSecurityQuestionsSetup === false) {
          hint.innerHTML = 'Security questions not set. <a href="/forgot.html">Set them up</a> for easier password recovery.';
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
    api(ACTIVE_ENDPOINT, token)
      .then(function (data) {
        renderDashboardForData(data);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        renderDashboardForData(null);
      });
  }

  function renderDashboardForData(data) {
    const card = qs('#activeLoanCard');
    const hero = qs('#dashBorrowHero');
    const allLoans = (data && data.allLoans) || [];
    const hasActive = !!(data && data.loan);

    // Cache active-loan status for sidebar.js to read without
    // duplicating the API call. Used to hide the "Request a new
    // loan" sidebar link when there's already one outstanding.
    try {
      sessionStorage.setItem('cif_has_active_loan', String(hasActive));
      sessionStorage.setItem('cif_has_active_loan_at', String(Date.now()));
      // Set the synchronous CSS hook + hide the link inline so
      // there's no flash on the dashboard page itself.
      document.documentElement.classList.toggle('cif-has-active-loan', !!hasActive);
      var newLoanLinks = document.querySelectorAll('.dash-sidebar-link[href="/request-loan.html"]');
      for (var i = 0; i < newLoanLinks.length; i++) {
        newLoanLinks[i].style.display = hasActive ? 'none' : '';
      }
    } catch (e) { /* sessionStorage disabled — fall back to sidebar.js fetch */ }

    // Branch: active loan → show the loan card; otherwise → show
    // the "Up to $X if approved" hero. Never both.
    if (hasActive) {
      if (hero) hero.hidden = true;
      if (card) {
        card.hidden = false;
        renderActiveLoan(card, data);
      }
    } else {
      if (card) card.hidden = true;
      if (hero) hero.hidden = false;
    }

    // Stats grid (always visible if we got a successful response)
    renderStatsGrid(allLoans);

    // Recent activity feed (replaces the legacy My-loans list)
    renderRecentActivity(allLoans);

    // Legacy My-loans list (no longer in markup but the function is
    // safe to call — it's a no-op when the target element is gone)
    renderLoanList(qs('#loanListBody'), allLoans);
    renderMemberSince(allLoans);
  }

  // ---------- Stats grid (Total borrowed + Member since) ----------
  function renderStatsGrid(allLoans) {
    const grid = qs('#dashStatsGrid');
    if (!grid) return;
    grid.hidden = false;

    // Count of loans is still useful for the "Member since" meta.
    let count = 0;
    allLoans.forEach(function (l) {
      const p = Number(l && l.principal);
      if (isFinite(p) && p > 0) { count += 1; }
    });

    // Member since: year of the earliest loan's loanDate / origination.
    const sinceEl = qs('#dashMemberSince');
    const sinceMeta = qs('#dashMemberSinceMeta');
    let earliest = null;
    allLoans.forEach(function (l) {
      const d = new Date(l.loanDate || l.originationDate || 0);
      if (!isNaN(d.getTime()) && (earliest === null || d < earliest)) {
        earliest = d;
      }
    });
    if (sinceEl) {
      if (earliest) {
        // "April 2026" — month name + year reads richer than year alone.
        sinceEl.textContent = earliest.toLocaleDateString('en-US', {
          month: 'long', year: 'numeric',
        });
      } else {
        sinceEl.textContent = '—';
      }
    }
    if (sinceMeta) {
      if (count > 1) {
        sinceMeta.textContent = count + ' loans · returning customer';
      } else if (count === 1) {
        sinceMeta.textContent = '1 loan · welcome back';
      } else {
        sinceMeta.textContent = '';
      }
    }
  }

  // ---------- Recent activity feed ----------
  function renderRecentActivity(allLoans) {
    const root = qs('#dashRecentActivity');
    if (!root) return;
    root.innerHTML = '';

    if (!allLoans || !allLoans.length) {
      const p = document.createElement('p');
      p.className = 'dash-recent-activity-empty';
      p.textContent = "Nothing here yet — your account activity will show up after your first loan.";
      root.appendChild(p);
      return;
    }

    // Newest first by loanDate / originationDate. Show top 4.
    const sorted = allLoans.slice().sort(function (a, b) {
      const da = new Date(a.loanDate || a.originationDate || 0).getTime();
      const db = new Date(b.loanDate || b.originationDate || 0).getTime();
      return db - da;
    }).slice(0, 4);

    sorted.forEach(function (loan) {
      const row = document.createElement('a');
      row.className = 'dash-recent-activity-row';
      row.href = '/loans.html?id=' + encodeURIComponent(loan.id);
      row.style.textDecoration = 'none';
      row.style.color = 'inherit';

      const status = (loan.status || '').toLowerCase();
      const isPaidOff = status.indexOf('paid') !== -1;
      const isPastDue = status.indexOf('past') !== -1 || (loan.daysLate && loan.daysLate.toLowerCase && loan.daysLate.toLowerCase() !== 'not late');

      // Icon + classes based on state
      const iconWrap = document.createElement('div');
      iconWrap.className = 'dash-recent-activity-icon ' +
        (isPaidOff ? 'dash-recent-activity-icon--paid'
         : isPastDue ? 'dash-recent-activity-icon--late'
         : 'dash-recent-activity-icon--current');
      iconWrap.innerHTML = isPaidOff
        ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
        : isPastDue
        ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
        : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>';

      const main = document.createElement('div');
      main.className = 'dash-recent-activity-main';

      const title = document.createElement('div');
      title.className = 'dash-recent-activity-title';
      title.textContent = isPaidOff ? 'Paid in full'
                       : isPastDue ? 'Loan past due'
                       : (loan.status || 'Loan');
      main.appendChild(title);

      const sub = document.createElement('div');
      sub.className = 'dash-recent-activity-sub';
      const dateStr = formatDate(loan.loanDate || loan.originationDate);
      sub.textContent = 'Loan #' + (loan.publicId || loan.id) + (dateStr && dateStr !== '—' ? ' · ' + dateStr : '');
      main.appendChild(sub);

      const right = document.createElement('div');
      right.className = 'dash-recent-activity-amount';

      const amt = document.createElement('div');
      amt.textContent = formatCurrencyPrecise(loan.principal);
      right.appendChild(amt);

      const status_el = document.createElement('span');
      status_el.className = 'dash-recent-activity-status';
      status_el.textContent = isPaidOff ? 'Closed'
                            : isPastDue ? 'Past due'
                            : (loan.status || 'Current');
      if (isPastDue) status_el.style.color = '#991b1b';
      right.appendChild(status_el);

      row.appendChild(iconWrap);
      row.appendChild(main);
      row.appendChild(right);
      root.appendChild(row);
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
        captionEl.textContent = 'Payment of ' + formatCurrencyPrecise(loan.nextDueAmount) +
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
