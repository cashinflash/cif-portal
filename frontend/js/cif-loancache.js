/* cif-loancache.js — stale-while-revalidate cache for the loan-card endpoints.

   The loan card on Home, Loans, and Payments is driven by a Vergent-backed
   endpoint (/api/my-loans/active for Home+Loans, /api/my-payment/loan-summary
   for Payments). Those endpoints make several SEQUENTIAL Vergent round-trips
   (fetch all loans + one history call per paid-off loan + e-sign check), so a
   cold call can take 5-7s. Without a cache, every page navigation re-pays that
   latency even though the data is identical to the page you just left.

   This caches the last good payload per endpoint in sessionStorage so a
   navigation paints the card INSTANTLY from cache, then refreshes in the
   background (stale-while-revalidate). The first load of a session still pays
   full latency once; every navigation after is instant.

   Safety:
   - Keyed to the signed-in customer (from the JWT) so a payload can NEVER leak
     across accounts — a cache from another customer is ignored.
   - Short TTL + the background refresh always corrects within one load, so a
     stale balance self-heals in seconds.
   - clear() is called on the events that change loan state (payment made, loan
     signed, sign-out) so the next card shows fresh data immediately.
   - Entirely best-effort: if sessionStorage is full/disabled the helpers no-op
     and pages behave exactly as before (plain fetch, no cache). */
(function (w) {
  'use strict';

  var STORE_KEY = 'cif_loancard_cache_v1';
  var TTL_MS = 90 * 1000; // background refresh corrects well within this window

  function cidFromToken() {
    try {
      var t = sessionStorage.getItem('cif_id_token');
      if (!t) return '';
      var part = t.split('.')[1];
      if (!part) return '';
      var json = atob(part.replace(/-/g, '+').replace(/_/g, '/'));
      var p = JSON.parse(json);
      return String(p['custom:vergentCustomerId'] || p.sub || '');
    } catch (e) { return ''; }
  }

  // Read the whole store, dropping it if it belongs to a different customer.
  function readStore() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (!obj || obj.cid !== cidFromToken()) return null;
      return obj;
    } catch (e) { return null; }
  }

  var CifLoanCache = {
    /* Return the cached payload for an endpoint (even if past TTL — the caller
       paints it instantly, then revalidates). null if absent / other customer. */
    get: function (endpoint) {
      var store = readStore();
      if (!store || !store.entries) return null;
      var e = store.entries[endpoint];
      return e ? e.data : null;
    },

    /* True only if the cached payload is still within TTL (rarely needed —
       SWR paints stale + revalidates regardless). */
    isFresh: function (endpoint) {
      var store = readStore();
      if (!store || !store.entries) return false;
      var e = store.entries[endpoint];
      return !!(e && (Date.now() - e.at) < TTL_MS);
    },

    set: function (endpoint, data) {
      try {
        var store = readStore() || { cid: cidFromToken(), entries: {} };
        if (!store.entries) store.entries = {};
        store.entries[endpoint] = { at: Date.now(), data: data };
        sessionStorage.setItem(STORE_KEY, JSON.stringify(store));
      } catch (e) { /* sessionStorage full/disabled — cache is best-effort */ }
    },

    clear: function () {
      try { sessionStorage.removeItem(STORE_KEY); } catch (e) { /* ignore */ }
    }
  };

  w.CifLoanCache = CifLoanCache;
})(window);
