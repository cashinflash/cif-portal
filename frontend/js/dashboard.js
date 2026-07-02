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
  const LOGIN_URL = '/login.html';

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
    // Populate every name slot in the redesigned Home (welcome heading,
    // desktop page-sub, desktop user chip) — all share .dash-first-name.
    qsa('.dash-first-name').forEach(function (el) { el.textContent = firstName || 'there'; });
    const greetEl = qs('#dashGreeting');
    if (greetEl) {
      const h = new Date().getHours();
      greetEl.textContent = h < 12 ? 'Good morning,' : (h < 18 ? 'Good afternoon,' : 'Good evening,');
    }

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
    wireAppActions();
    wireImageFallbacks();
    loadCards(token);
    showPaymentSuccessBanner();  // one-shot "payment posted" banner
    renderProfileFromClaims();   // instant render from JWT claims (legacy selectors safe to call when missing)
    loadProfileFromApi();         // hydrate with Vergent data (account status, phone hint, text-messaging flag)
    loadActiveLoan();
    // E-sign is now handled portal-wide by cif-esign.js (the "Awaiting
    // signature" card state + Review & sign prompt/modal), driven off the
    // active-loan response. The legacy amber banner is retired to avoid a
    // duplicate prompt; loadPendingEsign() is kept below but no longer called.
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

  // ---------- E-sign pending banner ----------
  // Vergent v1 /api/esign/pending/{cid} — amber banner when the
  // customer has at least one loan document waiting for signature.
  // Tap "Sign now" → Vergent's hosted signing page opens in a new
  // tab → customer signs → returns to our tab. The visibilitychange
  // / focus listeners installed below refetch /api/my-esign/pending
  // so the banner clears automatically once Vergent marks the doc
  // signed.
  function loadPendingEsign() {
    const token = sessionStorage.getItem('cif_id_token');
    if (!token) return;
    fetch('/api/my-esign/pending', {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      credentials: 'omit',
    }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    }).then(function (data) {
      const pending = (data && data.pending) || [];
      // Remove any existing banner before re-rendering so a second
      // call from the focus-listener can clear/refresh in place.
      const existing = document.querySelector('.dash-banner--esign');
      if (existing) existing.remove();
      if (pending.length) renderEsignBanner(pending);
    }).catch(function () { /* silent — leave banner off on network blip */ });
    setupEsignAutoRefresh();
  }

  // Auto-refresh the pending-sig banner when the tab regains focus
  // (i.e., the customer just came back from signing on Vergent's
  // hosted page in a new tab). Registered once per page load.
  function setupEsignAutoRefresh() {
    if (window.__cifEsignAutoRefreshSetup) return;
    window.__cifEsignAutoRefreshSetup = true;
    let lastChecked = Date.now();
    const refresh = function () {
      if (document.visibilityState !== 'visible') return;
      // Throttle to avoid hammering the endpoint on rapid focus
      // toggles (e.g. macOS spaces + window switching).
      const now = Date.now();
      if (now - lastChecked < 2000) return;
      lastChecked = now;
      const token = sessionStorage.getItem('cif_id_token');
      if (!token) return;
      fetch('/api/my-esign/pending', {
        headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
        credentials: 'omit',
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          const pending = (data && data.pending) || [];
          const existing = document.querySelector('.dash-banner--esign');
          if (existing) existing.remove();
          if (pending.length) renderEsignBanner(pending);
        }).catch(function () { /* silent */ });
    };
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('focus', refresh);
  }

  function renderEsignBanner(pending) {
    const first = pending[0] || {};
    const loanId = first.loanId || first.publicLoanId || '';
    const esignId = first.id || '';
    const count = pending.length;
    const banner = document.createElement('div');
    banner.className = 'dash-banner dash-banner--esign';
    const noun = count > 1 ? (count + ' documents') : '1 document';
    // Sign now opens Vergent's hosted signing page in a new tab.
    // Prefer the signingUrl that the backend resolved from
    // /esign/sign/{id} — the EsignId from /esign/pending isn't
    // always the GUID Vergent's URL wants. Fall back to the
    // EsignId-based URL only if resolution failed.
    const signHref = first.signingUrl
      || (esignId ? ('https://shared.vergentlms.com/esign?g=' + encodeURIComponent(esignId)) : '#');
    banner.innerHTML = (
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
      '<polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/></svg>' +
      '<span>You have <strong>' + noun + '</strong> waiting for your signature.</span>' +
      '<div class="dash-banner-actions">' +
      '  <a class="dash-banner-btn dash-banner-btn--primary" href="' + signHref + '" target="_blank" rel="noopener">Sign now</a>' +
      '</div>' +
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

  // ---------- Request a new loan ----------
  // Fast Re-Apply: "Request a new loan" now opens the native in-portal
  // flow at /request-loan.html. The old Vergent-handoff click-hijack was
  // removed so these links/buttons navigate normally.
  function wireNewLoanButton() { /* no-op: native /request-loan.html flow */ }

  // ---------- Fast Re-Apply status (Q3): pending / declined card ----------
  function reapplyHideApplyCtas(hidden) {
    ['#requestLoanBtn', '#requestLoanBtnMobile'].forEach(function (s) {
      var el = qs(s); if (el) el.style.display = hidden ? 'none' : '';
    });
    qsa('a.paidup-cta').forEach(function (el) { el.style.display = hidden ? 'none' : ''; });
    var nl = qs('.home-needloan'); if (nl) nl.style.display = hidden ? 'none' : '';
  }

  function reapplySlot() {
    var slot = qs('#reapplyStatusSlot');
    if (slot) return slot;
    slot = document.createElement('div');
    slot.id = 'reapplyStatusSlot';
    slot.style.cssText = 'margin:0 0 18px;max-width:920px;';
    // Insert full-width at the top of the content column (after the page
    // heading) so it spans properly on desktop instead of being trapped
    // in the narrow no-loan grid column.
    var main = qs('.app-main') || qs('main');
    if (main) {
      var head = main.querySelector('.app-pagehead');
      if (head && head.nextSibling) main.insertBefore(slot, head.nextSibling);
      else main.insertBefore(slot, main.firstChild);
    } else {
      var anchor = qs('#activeLoanCard') || qs('.dash-loan-empty');
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(slot, anchor);
      else document.body.appendChild(slot);
    }
    return slot;
  }

  function loadReapplyStatus(hasActive) {
    // An active loan takes precedence — its card shows, no RL status card.
    if (hasActive) {
      var s = qs('#reapplyStatusSlot'); if (s) s.innerHTML = '';
      reapplyHideApplyCtas(false);
      return;
    }
    api('/api/my-reapply/status', token).then(function (d) {
      renderReapplyStatus(d || {});
    }).catch(function () { /* fail soft — no card */ });
  }

  function renderReapplyStatus(d) {
    var state = d && d.state;
    var slot = reapplySlot();
    if (state === 'pending') {
      // Keep the Apply button visible — tapping it opens the friendly
      // "application is being reviewed" gate (consistent with the Loans
      // page) rather than the form. The card below just informs.
      reapplyHideApplyCtas(false);
      var amt = d.amount ? (' for ' + String(d.amount).replace(/[^0-9$.,]/g, '')) : '';
      slot.innerHTML =
        '<div style="background:#fff;border:1px solid #d7e6dd;border-radius:16px;padding:18px;' +
        'display:flex;gap:14px;align-items:flex-start;box-shadow:0 6px 20px rgba(16,40,34,.10);">' +
        '<div style="width:40px;height:40px;flex:none;border-radius:50%;background:#0E8741;color:#fff;' +
        'display:flex;align-items:center;justify-content:center;">' +
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></svg></div>' +
        '<div><div style="font-weight:800;color:#0f2a20;font-size:1.02rem;margin-bottom:3px;">Your application is under review</div>' +
        '<div style="color:#46535f;font-size:.9rem;line-height:1.5;">Your application' + amt + ' is being reviewed. We’ll notify you of the decision by email and text, typically within minutes during business hours.</div></div></div>';
      return;
    }
    if (state === 'declined') {
      reapplyHideApplyCtas(false);
      slot.innerHTML =
        '<div style="background:#fdf3f3;border:1px solid #f3c9c9;border-radius:16px;padding:18px;display:flex;gap:14px;align-items:flex-start;">' +
        '<div style="width:40px;height:40px;flex:none;border-radius:50%;background:#dc2626;color:#fff;' +
        'display:flex;align-items:center;justify-content:center;">' +
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>' +
        '<div><div style="font-weight:800;color:#5a0d0d;font-size:1.02rem;margin-bottom:3px;">Application not approved</div>' +
        '<div style="color:#7a4a4a;font-size:.9rem;line-height:1.5;">We’ve emailed you the details. You’re welcome to apply again, or call (888) 999-9859 with questions.</div></div></div>';
      return;
    }
    // none / funded → clear the card, restore apply CTAs.
    reapplyHideApplyCtas(false);
    slot.innerHTML = '';
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
    // Stale-while-revalidate: paint the card INSTANTLY from the last cached
    // payload (so navigating back to Home is instant), then refresh in the
    // background. The first load of a session still fetches normally; every
    // navigation after is instant. See cif-loancache.js.
    var cached = window.CifLoanCache && CifLoanCache.get(ACTIVE_ENDPOINT);
    if (cached) {
      try { renderDashboardForData(cached); } catch (e) { /* fall through to fetch */ }
    }
    api(ACTIVE_ENDPOINT, token)
      .then(function (data) {
        if (window.CifLoanCache) CifLoanCache.set(ACTIVE_ENDPOINT, data);
        renderDashboardForData(data);
      })
      .catch(function (err) {
        if (err && err.message === 'unauthorized') return;
        // Only fall back to the empty/error state if we had nothing cached.
        if (!cached) renderDashboardForData(null);
      });
  }

  // ---------- Auto-poll for a freshly-created loan ----------
  // After a customer applies/signs online, Vergent takes ~1 min to create the
  // loan + e-sign doc + populate its pending queue. The portal only checked on
  // page load, so the flip to "pending / review & sign" lagged. While there's no
  // active loan yet, poll briefly so it appears on its own — no manual reload.
  // Bounded (every 8s, ~1.5 min) and paused while the tab is hidden.
  var _pendingPollTimer = null;
  var _pendingPollTries = 0;
  function startPendingPoll() {
    if (_pendingPollTimer || window.__cifActiveLoan) return;
    _pendingPollTries = 0;
    _pendingPollTimer = setInterval(function () {
      _pendingPollTries++;
      if (_pendingPollTries > 12 || window.__cifActiveLoan) { stopPendingPoll(); return; }
      if (document.visibilityState === 'hidden') return;
      api(ACTIVE_ENDPOINT, token).then(function (data) {
        if (data && data.loan) {
          stopPendingPoll();
          if (window.CifLoanCache) CifLoanCache.set(ACTIVE_ENDPOINT, data);
          renderDashboardForData(data);
        }
      }).catch(function () { /* transient — keep polling */ });
    }, 8000);
  }
  function stopPendingPoll() {
    if (_pendingPollTimer) { clearInterval(_pendingPollTimer); _pendingPollTimer = null; }
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

    // Fast Re-Apply (Q3): show a pending/declined card for an in-flight
    // re-loan. Runs async; harmless if there's none.
    try { loadReapplyStatus(hasActive); } catch (e) { /* non-critical */ }

    // Branch: active loan → show the loan card; otherwise → show
    // the "Up to $X if approved" hero. Never both.
    if (hasActive) {
      if (hero) hero.hidden = true;
      if (card) {
        card.hidden = false;
        card.classList.remove('loan-card--art', 'loan-card--paidup', 'loan-card--firsttime');
        renderActiveLoan(card, data);
      }
    } else {
      if (card) {
        card.hidden = false;
        card.classList.remove('is-pastdue', 'is-pastdue-soft');
        card.classList.add('loan-card--paidup');
        card.setAttribute('aria-busy', 'false');
        var _sk = qs('.dash-card-skeleton', card); if (_sk) _sk.style.display = 'none';
        var _bd = qs('.dash-loan-body', card); if (_bd) _bd.hidden = true;
        var _emp = qs('.dash-loan-empty', card); if (_emp) _emp.hidden = false;
        // Returning customer (has prior loans, none active) vs first-timer:
        // tailor the hero copy + show the "paid up" status chips only when
        // they actually had a balance to clear.
        var _returning = allLoans.length > 0;
        var _pl = qs('[data-paidup-lead]', card);
        var _px = qs('[data-paidup-text]', card);
        var _pc = qs('[data-paidup-chips]', card);
        if (_returning) {
          if (_pl) { _pl.textContent = "No active loan right now."; _pl.hidden = false; }
          if (_px) _px.textContent = "When you need extra cash, you can request up to $255 quickly and securely.";
          if (_pc) _pc.hidden = false;
        } else {
          if (_pl) _pl.hidden = true;
          if (_px) _px.textContent = "Get up to $255 in minutes — quick, easy, and secure, with no hidden fees.";
          if (_pc) _pc.hidden = true;
        }
        // First-timers get a sparse hero (no lead, no chips) — tag the card so
        // the CSS centers the shorter content + art instead of letting the art
        // shrink and float in its slot.
        card.classList.toggle('loan-card--firsttime', !_returning);
      }
      // No active loan → show the composed "paid up / cash when you need it" hero.
      if (hero) hero.hidden = false;
    }

    // App layout: record state + toggle the active-only "Make a payment" CTA.
    // While the loan is awaiting signature, treat it as not-yet-payable — hide
    // the active-only pay CTAs so the Review & sign prompt is the clear action.
    window.__cifActiveLoan = hasActive;
    // Auto-poll for a just-created loan when none is showing yet; stop once one
    // appears (covers funded AND pending-signature loans).
    if (hasActive) stopPendingPoll(); else startPendingPoll();
    var _pendingSig = hasActive && data && data.loan && window.CifEsign && CifEsign.isPending(data.loan);
    // Persist + flag synchronously so the dashboard preflight can hide the pay
    // CTAs on the NEXT load with no flash (see the inline script in <head>).
    try { sessionStorage.setItem('cif_pending_signature', String(!!_pendingSig)); } catch (e) { /* ignore */ }
    document.documentElement.classList.toggle('cif-pending-signature', !!_pendingSig);
    qsa('[data-show-when-active]').forEach(function (el) {
      el.style.display = (hasActive && !_pendingSig) ? '' : 'none';
    });

    // Stats grid (always visible if we got a successful response)
    renderStatsGrid(allLoans);

    // Recent activity feed (replaces the legacy My-loans list)
    renderRecentActivity(allLoans);
    // Mirror the rendered activity into the mobile card.
    var _amob = qs('#dashRecentActivityMobile'); var _adesk = qs('#dashRecentActivity');
    if (_amob && _adesk) _amob.innerHTML = _adesk.innerHTML;

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
      root.innerHTML =
        '<div class="dash-recent-activity-empty">' +
        '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="8" y1="14" x2="13" y2="14"/></svg>' +
        '<p class="dash-recent-activity-empty-title">No activity yet</p>' +
        '<p class="dash-recent-activity-empty-sub">Your payments and loan history will appear here.</p>' +
        '</div>';
      return;
    }

    // Newest first by loanDate / originationDate. Show top 3 (matches the
    // example; keeps the card the same compact height as the pay card).
    const sorted = allLoans.slice().sort(function (a, b) {
      const da = new Date(a.loanDate || a.originationDate || 0).getTime();
      const db = new Date(b.loanDate || b.originationDate || 0).getTime();
      return db - da;
    }).slice(0, 3);

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

  // Whole days a loan is past its due date (0 if not past due / unknown).
  function daysPastDue(loan) {
    if (!loan || !loan.nextDueDate) return 0;
    var due = new Date(loan.nextDueDate);
    if (isNaN(due.getTime())) return 0;
    var today = new Date();
    var a = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
    var b = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    var days = Math.round((b - a) / 86400000);
    return days > 0 ? days : 0;
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

    // On a payment plan the headline "Amount Due" is the next installment;
    // otherwise it's the full balance (regular card — unchanged).
    // Show the plan installment only when one is actually due now (amountDue > 0).
    // After a plan payment Vergent reports amountDue = 0 (caught up); fall back to
    // the remaining balance so the card never shows a misleading $0.00.
    // Next plan payment: the live amountDue when one's due, else the remembered
    // installment (planInstallment) between due dates; otherwise the balance.
    var _inst = (loan.amountDue != null && loan.amountDue > 0) ? loan.amountDue
      : (loan.planInstallment != null && loan.planInstallment > 0 ? loan.planInstallment : null);
    var displayDue = (loan.hasPaymentPlan && _inst != null) ? _inst : loan.balance;
    setText(qs('[data-loan-balance]', card), formatCurrencyPrecise(displayDue).replace(/^\$/, ''));
    setText(qs('[data-loan-pay-amount]', card), formatCurrencyPrecise(loan.balance));
    setText(qs('[data-loan-principal]', card), formatCurrencyPrecise(loan.principal));
    setText(qs('[data-loan-next-due]', card), formatDate(loan.nextDueDate));
    setText(qs('[data-loan-next-amount]', card), formatCurrencyPrecise(loan.nextDueAmount));
    setText(qs('[data-loan-fee]', card), formatCurrencyPrecise(loan.fees));

    // Home "Make a payment" card lives OUTSIDE #activeLoanCard — query the
    // document so its amount-due + due-date mirror the loan card.
    setText(document.querySelector('[data-loan-pay-balance]'), formatCurrencyPrecise(displayDue).replace(/^\$/, ''));
    setText(document.querySelector('[data-loan-pay-due]'), formatDate(loan.nextDueDate));

    // Public loan id tag next to the "Active loan" heading.
    const idTag = qs('[data-loan-public-id]', card);
    if (idTag) {
      const pid = loan.publicId || loan.id;
      if (pid) {
        // Markup already prints the "Loan #" prefix — just fill the id.
        idTag.textContent = pid;
        idTag.hidden = false;
      } else {
        idTag.hidden = true;
      }
    }

    const autopayPill = qs('[data-loan-autopay]', card);
    if (autopayPill) autopayPill.hidden = !loan.autopay;

    renderProgress(card, loan);
    // The countdown chip moved into the Home pay card (outside the loan
    // card) — scope to the document so renderCountdown finds it.
    renderCountdown(document, loan);

    const captionEl = qs('[data-loan-caption]', card);
    if (captionEl) {
      if (loan.nextDueDate) {
        captionEl.textContent = 'Due ' + formatDate(loan.nextDueDate) + '.';
      } else {
        captionEl.textContent = 'Current balance remaining on your loan.';
      }
    }

    const pill = qs('[data-loan-status]', card);
    const note = qs('.loan-card-note', card);
    const noteText = qs('[data-note-text]', card);
    var GOOD_NOTE = 'Make your payment on time to keep your account in good standing.';
    var SOFT_NOTE = 'Your payment is past due. Please make a payment soon to keep your account in good standing.';
    var LATE_NOTE = 'Your payment is past due. Make a payment now to bring your account back into good standing.';
    if (pill) {
      const status = (loan.status || '').toLowerCase();
      const daysLate = (loan.daysLate || '').toLowerCase();
      pill.classList.remove('dash-pill--ok', 'dash-pill--warn', 'dash-pill--past-due');
      var isPastDue = (status.indexOf('past') !== -1 || status.indexOf('delinquent') !== -1 || (daysLate && daysLate !== 'not late'));
      // Recolor the whole hero by severity: amber 1–4 days, red 5+ (or when the
      // day count is unknown). The note icon is preserved — only the
      // [data-note-text] span changes.
      var dpd = isPastDue ? daysPastDue(loan) : 0;
      var soft = isPastDue && dpd >= 1 && dpd <= 4;
      var severe = isPastDue && !soft;
      card.classList.toggle('is-pastdue-soft', soft);
      card.classList.toggle('is-pastdue', severe);
      if (note) note.classList.toggle('is-pastdue-note', isPastDue);
      if (noteText) noteText.textContent = severe ? LATE_NOTE : (soft ? SOFT_NOTE : GOOD_NOTE);
      if (isPastDue) {
        pill.classList.add('dash-pill--past-due');
        pill.textContent = 'Past due';
      } else if (status.indexOf('grace') !== -1 || status.indexOf('pending') !== -1 || loan.isInRescindPeriod) {
        pill.classList.add('dash-pill--warn');
        pill.textContent = loan.isInRescindPeriod ? 'Rescind period' : loan.status;
      } else {
        pill.classList.add('dash-pill--ok');
        pill.textContent = 'Current';
      }
      // Bank (ACH) payment pending → consistent "Processing" pill + the strip
      // under the card (shared module; identical on payments + loans). Also
      // keeps the card out of any past-due styling.
      if (window.CifAch) {
        var ach = CifAch.info(loan);
        CifAch.renderStrip(ach);
        if (ach) {
          CifAch.applyPill(pill, ach);
          // Her repayment for this loan went out via ACH — show the bank as the
          // method on the card (precise "Checking •• 6789" when we have it from
          // the durable record), not whatever debit card is saved on file.
          CifAch.setRepayMethodBank(ach.account);
          // While pending, the Due Date figure becomes "Payment Clears" + the
          // estimated clear date (reverts automatically on return/clear).
          CifAch.applyClearDateFigure(ach);
          if (ach.state === 'pending') {
            // Processing is calm: green card, amber pill (the customer just
            // paid — never make paying look like it created a problem).
            card.classList.remove('is-pastdue', 'is-pastdue-soft');
            if (note) note.classList.remove('is-pastdue-note');
          } else if (ach.state === 'returned') {
            // Returned is trouble: deep-red card, matching the loans +
            // payments cards so the state reads the same portal-wide.
            card.classList.remove('is-pastdue-soft');
            card.classList.add('is-pastdue');
            if (note) note.classList.add('is-pastdue-note');
          }
          // Only block a SECOND payment while one is still PENDING. If it was
          // returned, let them pay again (the CTAs work normally).
          if (ach.state === 'pending') {
            var ctas = document.querySelectorAll('a.app-cta-primary[href*="payments.html"]');
            for (var ci = 0; ci < ctas.length; ci++) {
              if (ctas[ci].getAttribute('data-ach-bound')) continue;
              ctas[ci].setAttribute('data-ach-bound', '1');
              ctas[ci].addEventListener('click', function (e) {
                e.preventDefault();
                CifAch.showBlockedModal(ach);
              });
            }
          }
        }
      }
      // Awaiting e-signature → never present an unsigned, unfunded loan as a
      // healthy "Current" card. Show the "Awaiting signature" pill + the
      // Review & sign prompt, and route Make-a-Payment taps to signing.
      if (window.CifEsign) {
        var esign = CifEsign.infoForLoan(loan);
        CifEsign.renderStrip(esign);
        if (esign) {
          CifEsign.gateCard(card, loan);
          // Hide every Make-a-Payment CTA while unsigned (can't pay an unfunded loan).
          var esPay = document.querySelector('.home-pay');
          if (esPay) esPay.style.display = 'none';
          var esCtas = document.querySelectorAll('a.app-cta-primary[href*="payments.html"]');
          for (var ei = 0; ei < esCtas.length; ei++) { esCtas[ei].style.display = 'none'; }
        }
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
    const els = (card || document).querySelectorAll('[data-loan-countdown]');
    if (!els.length) return;
    let text = '', cls = '';
    if (loan.nextDueDate) {
      const due = new Date(loan.nextDueDate);
      if (!isNaN(due.getTime())) {
        // Day-granularity compare so "today" stays "today" all day.
        const today = new Date();
        const a = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
        const b = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
        const days = Math.round((a - b) / 86400000);
        if (days < 0) {
          text = Math.abs(days) + (Math.abs(days) === 1 ? ' day' : ' days') + ' past due';
          cls = 'is-late';
        } else if (days === 0) { text = 'Due today'; cls = 'is-soon'; }
        else if (days === 1) { text = 'Due tomorrow'; cls = 'is-soon'; }
        else { text = 'Due in ' + days + ' days'; if (days <= 7) cls = 'is-soon'; }
      }
    }
    els.forEach(function (el) {
      el.classList.remove('is-soon', 'is-late');
      if (!text) { el.hidden = true; return; }
      if (cls) el.classList.add(cls);
      el.textContent = text;
      el.hidden = false;
    });
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
  // ---------- App layout actions (re-loan gating, modal, More tab) ----------
  function wireAppActions() {
    var APPLY_URL = '/request-loan.html';  // Fast Re-Apply: native in-portal flow
    var modal = qs('#reloanModal');
    function requestLoan() {
      var active = window.__cifActiveLoan;
      if (typeof active === 'undefined') active = (sessionStorage.getItem('cif_has_active_loan') === 'true');
      if (active) { if (modal) modal.hidden = false; }
      else { window.location.href = APPLY_URL; }
    }
    var rl = qs('#requestLoanBtn'); if (rl) rl.addEventListener('click', requestLoan);
    var rlm = qs('#requestLoanBtnMobile'); if (rlm) rlm.addEventListener('click', requestLoan);
    var promo = qs('#promoRequestLoan'); if (promo) promo.addEventListener('click', requestLoan);
    qsa('[data-close-reloan]').forEach(function (el) {
      el.addEventListener('click', function () { if (modal) modal.hidden = true; });
    });
    var more = qs('#moreTab');
    if (more) more.addEventListener('click', function () {
      var menu = qs('#mobile-menu'), toggle = qs('#menu-toggle');
      if (menu) menu.classList.add('open');
      if (toggle) toggle.classList.add('active');
      document.body.style.overflow = 'hidden';
    });
  }

  // ---------- Customer-provided images with inline-SVG fallback ----------
  // Each <img data-fallback> is followed by a hidden <svg> recreation. If the
  // customer hasn't committed their PNG yet (404), swap to the SVG so the card
  // never shows a broken image. CSP-safe (no inline onerror attribute).
  function wireImageFallbacks() {
    qsa('img[data-fallback]').forEach(function (img) {
      function fail() {
        img.hidden = true;
        var svg = img.nextElementSibling;
        if (svg) svg.hidden = false;
      }
      img.addEventListener('error', fail);
      if (img.complete && img.naturalWidth === 0) fail();  // already failed (cached 404)
    });
  }

  // ---------- Repayment method: card on file (fallback shows default) ----------
  function loadCards(token) {
    if (!token) return;
    api('/api/my-cards', token).then(function (data) {
      var cards = (data && (data.cards || data.methods)) || [];
      // The repayment label appears in several places (desktop loan figure,
      // mobile loan foot, mobile "Saved debit card" tile) — set them all.
      var methodEls = document.querySelectorAll('[data-loan-repay-method]');
      var summaryEls = document.querySelectorAll('[data-card-summary]');
      if (cards.length) {
        var c = cards[0];
        var label = (c.brand || c.cardType || 'Card') + ' •• ' + (c.last4 || c.lastFour || '');
        // Skip the loan-card "Repayment method" label when an ACH payment is
        // active — CifAch.setRepayMethodBank() already set it to "Bank account"
        // (the flag guards against this async fetch stamping the card over it).
        if (!window.__cifAchMethodActive) {
          methodEls.forEach(function (el) { el.textContent = label; });
        }
        summaryEls.forEach(function (el) { el.textContent = label; });
      }
    }).catch(function () { /* leave the on-card defaults */ });
  }

  function wireSignOut() {
    function signOut() {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem('cif_access_token');
      sessionStorage.removeItem('cif_refresh_token');
      window.location.replace(LOGIN_URL + '?reason=signed_out');
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
    qsa('.mobile-menu-card, .mobile-nav-item a', menu).forEach(function (a) {
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
