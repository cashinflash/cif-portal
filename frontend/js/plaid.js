/* ═══════════════════════════════════════
   CASH IN FLASH — Plaid bank-link integration.

   Used on:
     /profile.html — full Bank accounts card with Connect button
                     and a list of currently-linked institutions.
     /dashboard.html — small "Connect your bank" CTA card for
                     customers without any connections yet.

   Backend endpoints (handlers/plaid.py):
     POST /api/plaid/link-token          — fresh link_token
     POST /api/plaid/exchange            — public_token → stored
     GET  /api/plaid/connections         — list of links
     DELETE /api/plaid/connections/{id}  — revoke

   Plaid Link SDK is lazy-loaded from cdn.plaid.com on first use.
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/start.html';

  function $(sel, root) { return (root || document).querySelector(sel); }
  function token() { return sessionStorage.getItem(TOKEN_KEY); }

  // ----- API helpers -----

  function api(path, options) {
    var t = token();
    if (!t) {
      window.location.replace(LOGIN_URL);
      return Promise.reject(new Error('unauthorized'));
    }
    options = options || {};
    var headers = options.headers || {};
    headers.Authorization = 'Bearer ' + t;
    headers.Accept = 'application/json';
    if (options.body && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
    return fetch(path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body || undefined,
      credentials: 'omit',
    }).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace(LOGIN_URL + '?reason=session_expired');
        throw new Error('unauthorized');
      }
      return r.json().then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      }).catch(function () {
        return { ok: r.ok, status: r.status, data: null };
      });
    });
  }

  // ----- Plaid SDK -----
  // The SDK is loaded statically via a <script> tag in
  // profile.html / dashboard.html `<head>`. This helper just
  // waits for `window.Plaid` to become available — handles the
  // race where the customer taps Connect before the async
  // script has finished loading. Dynamic <script> injection
  // was unreliable on iOS Safari (ITP / content blockers).
  function loadPlaidSdk() {
    return new Promise(function (resolve, reject) {
      if (window.Plaid && window.Plaid.create) return resolve(window.Plaid);
      var deadline = Date.now() + 6000;
      var iv = setInterval(function () {
        if (window.Plaid && window.Plaid.create) {
          clearInterval(iv);
          resolve(window.Plaid);
        } else if (Date.now() > deadline) {
          clearInterval(iv);
          reject(new Error('plaid_sdk_load_failed'));
        }
      }, 50);
    });
  }

  function fetchLinkToken() {
    return api('/api/plaid/link-token', { method: 'POST', body: '{}' })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.linkToken) {
          var err = new Error((res.data && res.data.error) || ('http_' + res.status));
          err.upstreamStatus = res.data && res.data.upstreamStatus;
          err.upstreamBody = res.data && res.data.upstreamBody;
          err.httpStatus = res.status;
          throw err;
        }
        return res.data.linkToken;
      });
  }

  function exchangePublicToken(publicToken, metadata) {
    return api('/api/plaid/exchange', {
      method: 'POST',
      body: JSON.stringify({ publicToken: publicToken, metadata: metadata }),
    });
  }

  function listConnections() {
    return api('/api/plaid/connections').then(function (res) {
      return (res.data && res.data.connections) || [];
    });
  }

  function disconnect(itemId) {
    return api('/api/plaid/connections/' + encodeURIComponent(itemId),
               { method: 'DELETE' });
  }

  // Open Plaid Link with a fresh token. onDone is called after a
  // successful exchange → caller refreshes the connections list.
  function openLink(onDone) {
    var btn = $('#bankConnectBtn') || $('#dashBankConnect');
    var originalText = btn ? btn.textContent : 'Connect your bank';
    if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
    return Promise.all([loadPlaidSdk(), fetchLinkToken()])
      .then(function (parts) {
        var Plaid = parts[0];
        var linkToken = parts[1];
        if (btn) { btn.disabled = false; btn.textContent = originalText; }
        if (!Plaid || !Plaid.create) {
          throw new Error('plaid_sdk_unavailable');
        }
        var handler = Plaid.create({
          token: linkToken,
          onSuccess: function (publicToken, metadata) {
            exchangePublicToken(publicToken, metadata).then(function (res) {
              if (res.ok && res.data && res.data.ok) {
                if (onDone) onDone(true);
              } else {
                console.warn('[plaid] exchange failed', res);
                window.alert('Connected to your bank but couldn’t save the link. Please try again, or call (747) 270-7121.');
                if (onDone) onDone(false);
              }
            });
          },
          onExit: function (err, _meta) {
            if (err) console.warn('[plaid] link exit with error', err);
          },
        });
        handler.open();
      })
      .catch(function (err) {
        if (btn) { btn.disabled = false; btn.textContent = originalText; }
        console.warn('[plaid] open failed', err);
        var msg = (err && err.message) || 'unknown';
        if (msg === 'unauthorized') return;  // already redirected
        var lines = ['We couldn’t open the bank-connect window.'];
        if (msg.indexOf('plaid_sdk') !== -1) {
          lines.push('Plaid SDK didn’t load — check your network or any ad-blockers.');
        } else if (err && err.httpStatus === 403) {
          lines.push('Backend route not registered (HTTP 403). Re-run provision-loans.yml so the new /api/plaid/* routes are added to the API.');
        } else if (err && err.httpStatus === 404) {
          lines.push('Backend route not found (HTTP 404). Re-run provision-loans.yml.');
        } else if (err && err.upstreamStatus !== undefined) {
          if (err.upstreamStatus === 0) {
            lines.push('Lambda couldn’t reach Plaid. Most likely PLAID_SECRET_ARN env var isn’t set — run provision-plaid.yml.');
          } else {
            lines.push('Plaid returned HTTP ' + err.upstreamStatus + '.');
          }
          if (err.upstreamBody) {
            lines.push('Detail: ' + String(err.upstreamBody).slice(0, 220));
          }
        } else {
          lines.push('Error: ' + msg);
        }
        lines.push('Please refresh and try again, or call (747) 270-7121.');
        window.alert(lines.join('\n\n'));
      });
  }

  // ----- Profile-page list rendering -----

  function fmtSubtype(s) {
    if (!s) return '';
    s = String(s).toLowerCase();
    if (s === 'checking') return 'Checking';
    if (s === 'savings') return 'Savings';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US',
      { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function renderBankList(connections) {
    var root = $('#bankList');
    if (!root) return;
    if (!connections.length) {
      root.innerHTML =
        '<p class="bank-empty">No bank accounts connected yet.</p>';
      return;
    }
    var html = connections.map(function (c) {
      var sub = fmtSubtype(c.accountSubtype);
      var mask = c.accountMask ? ('···' + c.accountMask) : '';
      var meta = [sub, mask].filter(Boolean).join(' · ');
      var when = c.linkedAt ? ('Connected ' + fmtDate(c.linkedAt)) : '';
      return (
        '<div class="bank-row" data-item-id="' + c.itemId + '">' +
        '  <div class="bank-row-icon" aria-hidden="true">' +
        '    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 14h6M9 18h6"/></svg>' +
        '  </div>' +
        '  <div class="bank-row-body">' +
        '    <div class="bank-row-name">' + escapeHtml(c.institutionName) + '</div>' +
        '    <div class="bank-row-meta">' + escapeHtml(meta) + '</div>' +
        (when ? '    <div class="bank-row-when">' + escapeHtml(when) + '</div>' : '') +
        '  </div>' +
        '  <button type="button" class="bank-row-remove" data-action="bank-disconnect" aria-label="Disconnect ' + escapeHtml(c.institutionName) + '">Disconnect</button>' +
        '</div>'
      );
    }).join('');
    root.innerHTML = html;
    root.querySelectorAll('[data-action="bank-disconnect"]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        var row = e.currentTarget.closest('.bank-row');
        var id = row && row.getAttribute('data-item-id');
        if (!id) return;
        if (!window.confirm('Disconnect this bank? You can reconnect any time.')) return;
        e.currentTarget.disabled = true;
        e.currentTarget.textContent = 'Disconnecting…';
        disconnect(id).then(function (res) {
          if (res.ok) {
            refresh();
          } else {
            e.currentTarget.disabled = false;
            e.currentTarget.textContent = 'Try again';
          }
        }).catch(function () {
          e.currentTarget.disabled = false;
          e.currentTarget.textContent = 'Try again';
        });
      });
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function refresh() {
    var root = $('#bankList');
    if (root) root.innerHTML = '<p class="dash-loading">Loading…</p>';
    return listConnections().then(renderBankList).then(function () {
      // Also refresh the dashboard CTA visibility, in case the
      // profile page is loaded inside the same SPA-ish session.
      maybeShowDashboardCta();
    });
  }

  // ----- Dashboard CTA card (only when no connections yet) -----

  function maybeShowDashboardCta() {
    var slot = $('#dashBankCta');
    if (!slot) return;
    listConnections().then(function (connections) {
      if (connections && connections.length) {
        slot.hidden = true;
        slot.innerHTML = '';
        return;
      }
      slot.hidden = false;
      slot.innerHTML =
        '<div class="dash-bank-cta">' +
        '  <div class="dash-bank-cta-icon" aria-hidden="true">' +
        '    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 14h6M9 18h6"/></svg>' +
        '  </div>' +
        '  <div class="dash-bank-cta-text">' +
        '    <strong>Connect your bank</strong>' +
        '    <p>Speed up future loan approvals — we securely link to your bank via Plaid.</p>' +
        '  </div>' +
        '  <button type="button" class="btn-apply" id="dashBankConnect">Connect your bank</button>' +
        '</div>';
      var btn = $('#dashBankConnect', slot);
      if (btn) btn.addEventListener('click', function () {
        openLink(function (ok) { if (ok) maybeShowDashboardCta(); });
      });
    }).catch(function () { /* silent */ });
  }

  // ----- Init -----

  function init() {
    // Profile page wiring
    var connectBtn = $('#bankConnectBtn');
    if (connectBtn) {
      connectBtn.addEventListener('click', function () {
        openLink(function (ok) { if (ok) refresh(); });
      });
      refresh();
    }

    // Dashboard CTA wiring
    if ($('#dashBankCta')) {
      maybeShowDashboardCta();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
