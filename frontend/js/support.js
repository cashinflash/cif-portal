/* ═══════════════════════════════════════
   CASH IN FLASH — Support page.
   Signed-in customer sends a message → POST /api/my-support → emailed to
   info@cashinflash.com (identity comes from the session, so nothing to re-type).
   ═══════════════════════════════════════ */
(function () {
  'use strict';

  var TOKEN_KEY = 'cif_id_token';
  var LOGIN_URL = '/login.html';
  function $(id) { return document.getElementById(id); }
  function token() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }

  function decodeJwt(t) {
    try {
      var b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      b64 = b64 + '==='.slice((b64.length + 3) % 4);
      return JSON.parse(decodeURIComponent(atob(b64).split('').map(function (c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join('')));
    } catch (e) { return null; }
  }

  function init() {
    if (!$('supSend')) return;  // not on the support page

    // Greet by name + show the email we'll reply to.
    var claims = token() ? decodeJwt(token()) : null;
    if (claims) {
      var first = (claims.given_name || '').trim();
      var email = (claims.email || '').trim();
      var who = $('supWho');
      if (who) who.textContent = email || (first ? first : 'your account');
    }

    var send = $('supSend');
    var errEl = $('supError');
    function showErr(msg) { if (errEl) { errEl.textContent = msg; errEl.hidden = false; } }
    function clearErr() { if (errEl) { errEl.hidden = true; errEl.textContent = ''; } }

    send.addEventListener('click', function () {
      clearErr();
      var t = token();
      if (!t) { window.location.replace(LOGIN_URL); return; }
      var reason = ($('supReason') || {}).value || 'general';
      var message = (($('supMessage') || {}).value || '').trim();
      if (message.length < 2) { showErr('Please type a message so we know how to help.'); var m = $('supMessage'); if (m) m.focus(); return; }

      send.disabled = true;
      var origText = send.textContent;
      send.textContent = 'Sending…';
      fetch('/api/my-support', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json', Accept: 'application/json' },
        credentials: 'omit',
        body: JSON.stringify({ reason: reason, message: message }),
      }).then(function (r) {
        if (r.status === 401 || r.status === 403) {
          try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) {}
          window.location.replace(LOGIN_URL + '?reason=session_expired');
          throw new Error('unauthorized');
        }
        return r.json().then(function (d) { return { ok: r.ok, data: d }; })
          .catch(function () { return { ok: r.ok, data: null }; });
      }).then(function (res) {
        if (res.ok && res.data && res.data.ok) {
          var form = $('supForm'); if (form) form.hidden = true;
          var done = $('supDone'); if (done) done.hidden = false;
          try { window.scrollTo(0, 0); } catch (e) {}
          return;
        }
        send.disabled = false; send.textContent = origText;
        showErr('We couldn’t send your message. Please try again, or call (888) 999-9859.');
      }).catch(function (e) {
        if (e && e.message === 'unauthorized') return;
        send.disabled = false; send.textContent = origText;
        showErr('Network error. Please try again, or call (888) 999-9859.');
      });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
