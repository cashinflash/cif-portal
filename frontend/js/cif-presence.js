/* ═══════════════════════════════════════════════════════════════════
   CASH IN FLASH — presence heartbeat (admin "online" dot)

   Loaded on every authed page (dashboard, loans, payments, profile).
   While the customer's tab is open and visible, this pings
   POST /api/presence/ping every ~45s so the operator Customers page in
   admin can show a live online / offline dot + "last seen" time.

   Design rules (this must NEVER affect the customer experience):
     • Completely isolated — touches no auth, no session, no UI. It only
       fires a fire-and-forget fetch and ignores the response.
     • Fail-silent — every path is wrapped so a network/permission error,
       a missing token, or a blocked request can never throw into the
       page or interfere with anything else on it.
     • Visible-only — a hidden/backgrounded tab does not ping, so the
       dot reflects someone actually looking at the portal. It pings
       immediately when the tab becomes visible again.

   The backend (loans.py: record_presence) stamps lastSeenAt keyed on the
   Cognito `sub` from the JWT and treats a ping within the last 90s as
   "online". Pinging at 45s gives two pings per window, so a single
   dropped ping never flips the customer to offline.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var PING_MS = 45000;        // heartbeat cadence (backend online window is 90s)
  var _timer = null;
  var _lastPingAt = 0;        // throttle: never ping more than once per ~20s

  function token() {
    try { return sessionStorage.getItem('cif_id_token'); } catch (e) { return null; }
  }

  // Fire-and-forget ping. Returns nothing, never rejects out of here.
  function ping() {
    try {
      if (document.visibilityState && document.visibilityState !== 'visible') return;
      var now = Date.now();
      if (now - _lastPingAt < 20000) return;   // de-dupe rapid visibility flaps
      var t = token();
      if (!t) return;
      _lastPingAt = now;
      fetch('/api/presence/ping', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
        credentials: 'omit',
        keepalive: true
      }).catch(function () { /* offline / blocked — ignore */ });
    } catch (e) { /* never let the heartbeat surface an error */ }
  }

  function onVisible() {
    try { if (document.visibilityState === 'visible') ping(); } catch (e) {}
  }

  function start() {
    try {
      ping();                                   // stamp online immediately on load
      if (_timer) return;
      _timer = setInterval(ping, PING_MS);
      document.addEventListener('visibilitychange', onVisible, false);
      // bfcache restore (Back/Forward) — re-stamp without a full reload
      window.addEventListener('pageshow', onVisible, false);
    } catch (e) { /* heartbeat is best-effort; swallow */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, false);
  } else {
    start();
  }
})();
