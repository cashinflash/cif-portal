"""
Customer Portal — Payments handler.

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-cards                 -> list the customer's saved cards
  GET  /api/my-banks                 -> list the customer's saved banks
  GET  /api/my-payment/loan-summary  -> active loan data formatted for the pay page
  POST /api/my-payment               -> mint a single-use Vergent customer-portal
                                        handoff URL (pointing at the loan's
                                        payment summary page); the frontend
                                        embeds it in an iframe modal so the
                                        UX feels in-portal.

Why a handoff (not a server-to-server charge):

Server-side charging is blocked by Vergent. Across the session we
proved every API path either crashes or rejects:

  * /V1/PostCustomerLoanPayment           → 500 NullReferenceException
  * /V1/repay/transaction/card[/sync]     → webhook receivers, not charge
                                            endpoints (schema includes
                                            post-charge artifacts)
  * /api/CustomerPortal/.../CreditCardPayment via service APIM token
                                          → 500 DependencyResolutionException
                                            (DI graph requires customer-
                                            scoped auth context)
  * /api/CustomerPortal/AuthenticateCognito on APIM proxy
                                          → 500 NullReferenceException
                                            (broken on Vergent's tenant)
  * /api/CustomerPortal/AuthenticateCognito on direct host
                                          → 404 (not exposed there)
  * /api/authenticate/handoff/create response `token` field
                                          → 36-char GUID, not a JWT;
                                            CreditCardPayment with it
                                            returns DependencyResolutionException

The only customer-scoped JWT Vergent will mint for our tenant is via
the email + 2FA code flow done in a real browser, which can't be
replicated from a Lambda.

So our charge "endpoint" is: mint a handoff URL (which Vergent's
endpoint already issues correctly) and let the frontend embed
Vergent's hosted payment page in an iframe modal. The customer pays
in Vergent's UI; we poll our loan-summary endpoint to detect when
the balance updates.

Environment:
  VERGENT_APIM_BASE_URL  default https://prod.apim.vergentlms.com/external/shared
  VERGENT_V1_BASE_URL    default https://shared.vergentlms.com/api/api
  VERGENT_SECRET_ARN     Secrets Manager ARN (same secret as loans.py)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

# Reuse everything from the loans handler rather than re-implementing.
# Both files ship in the same zip so the import resolves at cold start.
from handlers.loans import (
    APIM_BASE,
    CORS_HEADERS,
    V1_BASE,
    _claims,
    _customer_id,
    _get_apim_token,
    _get_creds,
    _get_v1_token,
    _http,
    _json_response,
    _secrets,
    _shape_v1_loan,
    _v1_get,
)

VERGENT_COMPANY_ID = int(os.environ.get("VERGENT_COMPANY_ID", "386"))

log = logging.getLogger()
log.setLevel(logging.INFO)


# ─────────────────────────────────────────
# Shape helpers
# ─────────────────────────────────────────
# Card-type id → display brand. Vergent v1's GetCustomerCardTypes
# returns the source-of-truth list at runtime; this is a fallback for
# the most common four. Confirmed empirically — adjust if a different
# id surfaces in CloudWatch.
# Static-fallback brand→id guesses. Only used if GetCustomerCardTypes
# fails; Vergent is the source of truth and we cache their mapping
# module-globally at first use.
_CARD_TYPE_NAMES = {
    1: "Visa",
    2: "MasterCard",
    3: "Amex",
    4: "Discover",
}
_BRAND_TO_TYPE_ID = {
    "Visa": 1,
    "MasterCard": 2,
    "Amex": 3,
    "Discover": 4,
}

# Per-container cache. Reset on cold start. {lower_brand_name: int_id}
_card_types_by_name: Optional[Dict[str, int]] = None
_card_types_by_id: Optional[Dict[int, str]] = None


def _brand_key(s: str) -> str:
    """Normalize a brand string for matching across Vergent's inconsistencies."""
    s = (s or "").strip().lower()
    # Collapse any whitespace and common variants.
    s = s.replace("master card", "mastercard")
    s = s.replace("american express", "amex")
    s = s.replace(" ", "")
    return s


def _load_card_types() -> None:
    """Populate _card_types_by_name from Vergent once per warm container.

    Vergent returns a FLAT dict {"Visa": 2, "MasterCard": 1, ...} —
    not the list-of-objects Swagger suggests. Handle both shapes.
    """
    global _card_types_by_name, _card_types_by_id
    if _card_types_by_name is not None:
        return
    status, body, _raw = _v1_request("GET", "/V1/GetCustomerCardTypes")
    names: Dict[str, int] = {}
    ids: Dict[int, str] = {}
    if status == 200 and isinstance(body, dict):
        # Flat-dict format {name: id} — observed on our tenant.
        flat_ok = True
        for k, v in body.items():
            try:
                names[_brand_key(str(k))] = int(v)
                ids[int(v)] = str(k)
            except (TypeError, ValueError):
                flat_ok = False
                break
        if not flat_ok:
            names.clear(); ids.clear()
            # Try nested variants: {CardTypes: [...]}, {items: [...]}
            items = body.get("CardTypes") or body.get("items") or body.get("Items")
            if isinstance(items, list):
                for t in items:
                    if isinstance(t, dict):
                        name = (t.get("name") or t.get("Name") or t.get("TypeName") or "").strip()
                        tid = t.get("id") or t.get("Id") or t.get("TypeId")
                        if name and tid is not None:
                            try:
                                tid_int = int(tid)
                            except (TypeError, ValueError):
                                continue
                            names[_brand_key(name)] = tid_int
                            ids[tid_int] = name
    elif status == 200 and isinstance(body, list):
        for t in body:
            if isinstance(t, dict):
                name = (t.get("name") or t.get("Name") or t.get("TypeName") or "").strip()
                tid = t.get("id") or t.get("Id") or t.get("TypeId")
                if name and tid is not None:
                    try:
                        tid_int = int(tid)
                    except (TypeError, ValueError):
                        continue
                    names[_brand_key(name)] = tid_int
                    ids[tid_int] = name

    if not names:
        log.warning("GetCustomerCardTypes yielded no usable mapping; falling back to static guesses. body=%s",
                    str(body)[:300] if body else None)
        names = {_brand_key(k): v for k, v in _BRAND_TO_TYPE_ID.items()}
        ids = {v: k for k, v in _BRAND_TO_TYPE_ID.items()}
    else:
        log.info("GetCustomerCardTypes loaded: %s", ids)
    _card_types_by_name = names
    _card_types_by_id = ids


def _vergent_card_type_id(brand: str) -> int:
    """Translate our detected brand name → Vergent's numeric card_type_id."""
    _load_card_types()
    return (_card_types_by_name or {}).get(_brand_key(brand), 0)


def _shape_card_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent v1's customer_card → UI shape."""
    # Prefer the explicit last_four_digits field; fall back to derived.
    last4 = (raw.get("last_four_digits") or "").strip()
    if not last4:
        masked = (raw.get("card_number") or "")
        digits = [c for c in masked if c.isdigit()]
        last4 = "".join(digits[-4:]) if len(digits) >= 4 else ""
    type_id = raw.get("card_type_id") or 0
    try:
        type_id_int = int(type_id)
    except (TypeError, ValueError):
        type_id_int = 0
    # Prefer the live mapping from Vergent; fall back to our static table.
    _load_card_types()
    brand = (_card_types_by_id or {}).get(type_id_int) or _CARD_TYPE_NAMES.get(type_id_int, "Card")
    # Vergent's processor field name is inconsistent across endpoints —
    # the same value can come back as CardProcessor (Pascal),
    # cardProcessor (camel), or card_processor_type (snake). Take the
    # first non-empty one.
    processor = (
        raw.get("CardProcessor")
        or raw.get("cardProcessor")
        or raw.get("card_processor_type")
        or ""
    )
    return {
        "id": raw.get("id"),
        "brand": brand,
        "last4": last4,
        "expMonth": raw.get("exp_month") or raw.get("expire_month"),
        "expYear": raw.get("exp_year") or raw.get("expire_year"),
        "isExpired": False,
        "isActive": bool(raw.get("is_active")),
        "isExisting": bool(raw.get("is_existing")),
        "status": raw.get("status") or "",
        "processor": processor,
        "cardRef": raw.get("card_ref") or raw.get("cardRef") or "",
        "cardGuid": raw.get("card_guid") or raw.get("card_account_guid") or "",
    }


def _apim_call(method: str, path: str, *,
               body: Optional[Dict[str, Any]] = None,
               extra_headers: Optional[Dict[str, str]] = None
               ) -> tuple:
    """Call a Vergent APIM endpoint with our service JWT + x-api-key."""
    tok = _get_apim_token()
    if not tok:
        return 0, None, ""
    creds = _get_creds()
    h = {
        "Authorization": f"Bearer {tok}",
        "x-api-key": creds["xApiKey"],
    }
    if extra_headers:
        h.update(extra_headers)
    return _http(f"{APIM_BASE}{path}", method, body=body, headers=h)




# ─────────────────────────────────────────
# Vergent v1 helpers
# ─────────────────────────────────────────
def _v1_request(method: str, path: str, *,
                body: Optional[Dict[str, Any]] = None
                ) -> tuple:
    """Call a Vergent v1 LMS endpoint with the service Token header.

    Same auth pattern as `loans.py::_v1_get` but supports any method
    and returns the raw response body too (for debugging upstream
    errors). Refreshes the token once on 401/403 then retries.
    """
    tok = _get_v1_token()
    if not tok:
        return 0, None, ""
    url = f"{V1_BASE}{path}"
    status, parsed, raw = _http(url, method, body=body, headers={"Token": tok})
    if status in (401, 403):
        # Force token refresh and retry once.
        from handlers import loans as _loans
        _loans._v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, parsed, raw = _http(url, method, body=body, headers={"Token": tok2})
    return status, parsed, raw


# ─────────────────────────────────────────
# Repay-via-Vergent payment endpoints (Phase Z)
# ─────────────────────────────────────────
# Vergent exposes direct Repay-gateway wrappers under /V1/repay/transaction/*.
# These sidestep the persistent failures of /V1/PostCustomerLoanPayment
# (NullReferenceException for un-tokenized cards) and v2 CustomerPortal
# CreditCardPayment (DependencyResolutionException). Same v1 service-token
# auth as every other working v1 endpoint we use.
#
# Body shape isn't fully documented; we send a generous set of fields
# in both PascalCase and snake_case so Vergent picks whatever it
# recognizes (same belt-and-suspenders pattern that worked in Phase W).
# Diagnostic surfacing on failure shows the verbatim upstream body
# so we can iterate field names without redeploying.



# ─────────────────────────────────────────
# OmniaPay — iframe session creation for customer-self-service Add Card
# ─────────────────────────────────────────
_omniapay_creds_cache: Optional[Dict[str, str]] = None
# Once a probe finds a working endpoint + auth + body shape, lock to it
# so warm invocations skip the dance.
_omniapay_session_path: Optional[str] = None
_omniapay_session_auth_header: Optional[str] = None
_omniapay_session_body_shape: Optional[str] = None


def _get_omniapay_creds() -> Optional[Dict[str, str]]:
    """Fetch OmniaPay credentials from Secrets Manager, cached per container.

    Expected shape (set manually via AWS Console at
    cif-portal/omniapay/credentials):
      apiKey:  Vergent-issued OmniaPay API key
      apiUrl:  https://api.omniapay.com (override via env if needed)
    """
    global _omniapay_creds_cache
    if _omniapay_creds_cache:
        return _omniapay_creds_cache
    try:
        resp = _secrets.get_secret_value(SecretId=OMNIAPAY_SECRET_ARN)
        _omniapay_creds_cache = json.loads(resp["SecretString"])
        return _omniapay_creds_cache
    except Exception as e:
        log.warning("omniapay secret read failed arn=%s err=%s",
                    OMNIAPAY_SECRET_ARN, e)
        return None


def _extract_session_guid(body: Any) -> Optional[str]:
    """Pull the iframe-session GUID out of OmniaPay's response.

    Try the common keys; OmniaPay's exact response shape isn't
    documented for us yet so we accept multiple plausible names.
    """
    if not isinstance(body, dict):
        return None
    for key in ("guid", "sessionId", "session_id", "iframeId",
                "iframe_id", "id", "token", "key", "uuid"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Sometimes wrapped: {data: {...}}, {result: {...}}, {session: {...}}
    for container in ("data", "result", "session", "iframe"):
        inner = body.get(container)
        if isinstance(inner, dict):
            guid = _extract_session_guid(inner)
            if guid:
                return guid
    return None


def _create_omniapay_session(customer_id: str,
                             referer_url: str) -> Optional[Dict[str, Any]]:
    """Create an OmniaPay iframe session and return iframe URL + GUID.

    Probes a small set of likely endpoint paths + auth header schemes +
    body shapes until one returns a 2xx with a parseable GUID. Locks to
    the winning combo for warm invocations. Logs every probe attempt so
    we can iterate based on what OmniaPay actually accepts.

    Returns {"iframeUrl": "...", "guid": "..."} on success, or None.
    """
    global _omniapay_session_path
    global _omniapay_session_auth_header
    global _omniapay_session_body_shape

    creds = _get_omniapay_creds()
    if not creds:
        return None
    api_key = creds.get("apiKey") or ""
    api_url = (creds.get("apiUrl") or OMNIAPAY_API_BASE).rstrip("/")
    if not api_key:
        log.warning("omniapay creds missing apiKey; skipping session creation")
        return None

    # Candidate POST paths — most likely first.
    paths = [
        "/cardtokens",
        "/sessions",
        "/v1/cardtokens",
        "/v1/sessions",
        "/iframe/sessions",
        "/cardtokens/sessions",
    ]
    # Candidate auth headers.
    auth_variants = [
        ("Authorization", f"Bearer {api_key}"),
        ("X-API-Key", api_key),
        ("apikey", api_key),
        ("X-Auth-Token", api_key),
    ]
    # Candidate body shapes. refererUrls matches what we saw on
    # iframe.omniapay.com/{guid}?refererUrls=...
    body_variants = {
        "minimal": {"refererUrls": referer_url},
        "with_customer": {
            "customerId": customer_id,
            "refererUrls": referer_url,
        },
        "snake": {
            "customer_id": customer_id,
            "referer_urls": referer_url,
        },
        "merchant": {
            "merchantId": creds.get("merchantId") or "",
            "customerId": customer_id,
            "refererUrls": referer_url,
        },
    }

    # Build the candidate list. If we already locked one, try it first.
    candidates = []
    if (_omniapay_session_path and _omniapay_session_auth_header
            and _omniapay_session_body_shape):
        candidates.append((
            _omniapay_session_path,
            _omniapay_session_auth_header,
            _omniapay_session_body_shape,
        ))
    for p in paths:
        for ah_name, ah_val in auth_variants:
            for bn in body_variants.keys():
                key = (p, ah_name, bn)
                already = (
                    _omniapay_session_path == p
                    and _omniapay_session_auth_header == ah_name
                    and _omniapay_session_body_shape == bn
                )
                if not already:
                    candidates.append((p, ah_name, bn))

    for path, auth_header_name, body_name in candidates:
        url = f"{api_url}{path}"
        body = body_variants[body_name]
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            auth_header_name: (
                f"Bearer {api_key}" if auth_header_name == "Authorization"
                else api_key
            ),
        }
        status, parsed, raw = _http(url, "POST", body=body, headers=headers)
        log.info(
            "omniapay probe url=%s auth=%s body=%s status=%s parsed_keys=%s raw_head=%r",
            url,
            auth_header_name,
            body_name,
            status,
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
            (raw or "")[:200].replace("\n", " "),
        )
        if status not in (200, 201):
            continue
        guid = _extract_session_guid(parsed)
        if not guid:
            log.warning("omniapay 2xx but no parseable guid: %r", (raw or "")[:300])
            continue

        # Lock the winning combo.
        _omniapay_session_path = path
        _omniapay_session_auth_header = auth_header_name
        _omniapay_session_body_shape = body_name

        iframe_url = (
            f"{OMNIAPAY_IFRAME_BASE.rstrip('/')}/{guid}"
            f"?refererUrls={referer_url}"
        )
        log.info("omniapay session created guid=%s path=%s body=%s",
                 guid, path, body_name)
        return {"iframeUrl": iframe_url, "guid": guid}

    log.warning("omniapay session creation: no candidate combo worked")
    return None


# ─────────────────────────────────────────
# Loan lookup — shared by loan-summary + payment validation
# ─────────────────────────────────────────
def _fetch_active_loan(cid: str) -> Optional[Dict[str, Any]]:
    """Return the customer's first outstanding loan (shaped), or None."""
    status, body = _v1_get(f"/V1/{cid}/loans")
    if status != 200 or not isinstance(body, list):
        return None
    shaped = [_shape_v1_loan(item) for item in body if isinstance(item, dict)]
    outstanding = [l for l in shaped if l.get("isOutstanding")]
    if outstanding:
        return outstanding[0]
    return shaped[0] if shaped else None


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_my_cards(event: Dict[str, Any]) -> Dict[str, Any]:
    """List the signed-in customer's saved cards via Vergent v1.

    Calls GET /api/V1/GetCustomerCards?custId=<cid> with the service
    Token header. v1's customerId-in-querystring auth model means we
    can use our service token without needing AuthenticateCognito
    (which is broken for our tenant).

    Pass ?debug=1 to get back the raw Vergent count, the raw first
    record's keys (no PII values), and which cards survived filtering.
    Used for diagnosing "card was added in admin but not visible in
    portal" cases — strip the debug fields before showing a real
    customer.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    debug = ((event.get("queryStringParameters") or {}).get("debug") == "1")
    if not cid:
        return _json_response(200, {"cards": [], "expiredCards": []})

    status, body, raw = _v1_request("GET", f"/V1/GetCustomerCards?custId={cid}")
    if status != 200 or not isinstance(body, list):
        log.warning("GetCustomerCards status=%s raw=%s", status, (raw or "")[:300])
        resp = {"cards": [], "expiredCards": [], "error": "upstream_unavailable"}
        if debug:
            resp["debug"] = {
                "vergentStatus": status,
                "vergentRaw": (raw or "")[:600],
            }
        return _json_response(200, resp)

    # Log full list so we can compare against the Vergent admin UI and
    # see whether our PostCustomerCard outputs are actually persisted.
    summary = [
        {
            "id": c.get("id"),
            "type_id": c.get("card_type_id"),
            "holder": c.get("card_holder"),
            "last4": "".join(ch for ch in (c.get("card_number") or "") if ch.isdigit())[-4:],
            "is_existing": c.get("is_existing"),
            "is_active": c.get("is_active"),
            "CardProcessor": c.get("CardProcessor"),
            "card_processor_type": c.get("card_processor_type"),
        }
        for c in body if isinstance(c, dict)
    ]
    log.info("GetCustomerCards cid=%s count=%s cards=%s", cid, len(summary), summary)

    shaped = [_shape_card_v1(c) for c in body if isinstance(c, dict)]
    # Vergent's GetCustomerCards returns *every* customer_card row,
    # including ghost records from earlier failed add-card attempts
    # (the same last4 may appear several times — only the newest
    # row with status==1 is the "current" record visible in Vergent
    # admin). The admin UI filters to status==1 and so do we.
    #
    # Fallbacks accept cards that pre-date the status field but
    # have other proof they're chargeable (a Repay token, an
    # OmniaPay GUID, or a non-empty processor string). last4 alone
    # is NOT enough — a row with only last4 is almost certainly a
    # ghost from a failed earlier save attempt.
    def _is_usable(c: Dict[str, Any]) -> bool:
        if c.get("status") == 1:
            return True
        proc = (c.get("processor") or "").strip()
        if proc and proc != "None":
            return True
        if (c.get("cardRef") or "").strip():
            return True
        if (c.get("cardGuid") or "").strip():
            return True
        return False

    active = [c for c in shaped if _is_usable(c)]
    resp: Dict[str, Any] = {"cards": active, "expiredCards": []}
    if debug:
        # Raw key list for the first record only (no values — avoids
        # leaking last4/exp/etc into a debug dump). Plus per-card
        # filter outcome so we can see why a card was excluded.
        first_keys = sorted(body[0].keys()) if body and isinstance(body[0], dict) else []
        outcomes = []
        for s in shaped:
            outcomes.append({
                "id": s.get("id"),
                "isActive": s.get("isActive"),
                "isExisting": s.get("isExisting"),
                "status": s.get("status"),
                "processor": s.get("processor"),
                "hasCardRef": bool(s.get("cardRef")),
                "hasCardGuid": bool(s.get("cardGuid")),
                "last4": s.get("last4"),
                "kept": _is_usable(s),
            })
        resp["debug"] = {
            "queriedCustomerId": cid,
            "vergentRawCount": len(body),
            "firstRecordKeys": first_keys,
            "filterOutcomes": outcomes,
        }
    return _json_response(200, resp)


def get_loan_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None})
    loan = _fetch_active_loan(cid)
    return _json_response(200, {"loan": loan})


def _luhn_ok(digits: str) -> bool:
    """Checksum-validate a card number. Purely defensive — Vergent will
    reject bad PANs on its side too."""
    if not digits or not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _detect_card_type(digits: str) -> str:
    """BIN-based brand detection. Matches Vergent's enum values where
    possible; falls back to 'Other'."""
    if not digits:
        return "Other"
    if digits.startswith("4"):
        return "Visa"
    if digits[:2] in {"34", "37"}:
        return "Amex"
    if digits.startswith("6011") or digits[:2] == "65" or (622126 <= int(digits[:6] or 0) <= 622925):
        return "Discover"
    if digits[:2] in {"51", "52", "53", "54", "55"} or (
        2221 <= int(digits[:4] or 0) <= 2720
    ):
        return "MasterCard"
    return "Other"


def post_card(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-cards — DISABLED for PCI SAQ A compliance.

    Self-service Add Card is intentionally turned off in the portal.
    Cards are added by Cash in Flash agents via Vergent's admin UI
    (which performs server-side Repay tokenization on Vergent's
    infrastructure). This keeps PAN entirely off our infrastructure.

    Returns 410 Gone immediately — never parses the body, never
    touches cardholder data. To re-enable, design a PCI-compliant
    PAN flow first (e.g. Repay Hosted Fields iframe so PAN goes
    browser → Repay, never through this Lambda).
    """
    log.info("post_card invoked while disabled — returning 410")
    return _json_response(410, {
        "error": "self_service_disabled",
        "message": "Card entry is handled by Cash in Flash agents at (747) 270-7121 or any store location.",
    })


def _extract_last4(candidates) -> str:
    """Given any string-ish, pull the trailing 4 digits. Returns '' if
    fewer than 4 digits are present anywhere in the string."""
    for c in candidates:
        if not c:
            continue
        digits = [ch for ch in str(c) if ch.isdigit()]
        if len(digits) >= 4:
            return "".join(digits[-4:])
    return ""


def _shape_bank_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent v1 customer_bank → UI shape.

    Field names are inconsistent across Vergent's v1 surfaces so we
    check every variant we've seen before giving up.
    """
    last4 = _extract_last4([
        raw.get("account_number"), raw.get("AccountNumber"),
        raw.get("account_number_masked"), raw.get("AccountNumberMasked"),
        raw.get("MaskedAccountNumber"), raw.get("AcctLast4"),
        raw.get("last4"), raw.get("Last4"),
        raw.get("AccountNum"),
    ])
    type_id = raw.get("account_type_id") or raw.get("AccountTypeId") or raw.get("type_id") or 0
    try:
        type_id_int = int(type_id) if type_id not in (None, "") else 0
    except (TypeError, ValueError):
        type_id_int = 0
    type_name = {1: "Checking", 2: "Savings"}.get(type_id_int, "Checking")
    return {
        "id": raw.get("id") or raw.get("Id") or raw.get("bank_id"),
        "name": (raw.get("bank_name") or raw.get("name") or raw.get("Name")
                 or raw.get("BankName") or "Bank"),
        "last4": last4,
        "accountType": type_name,
        "isPrimary": bool(raw.get("is_primary") or raw.get("IsPrimary")),
    }


def get_my_banks(event: Dict[str, Any]) -> Dict[str, Any]:
    """List the signed-in customer's saved bank accounts (ACH) via v1.

    Primary source: /api/V1/GetCustomerBanks?custId=<cid>. If that
    returns an empty list, fall back to the bank embedded on the
    active loan (LoanDetail.AccountNum). Vergent originations usually
    capture the customer's bank on the loan itself, and that field is
    always a masked string we can show.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"banks": []})

    status, body, raw = _v1_request("GET", f"/V1/GetCustomerBanks?custId={cid}")
    shaped: list = []
    if status == 200 and isinstance(body, list):
        shaped = [_shape_bank_v1(b) for b in body if isinstance(b, dict)]
        # One-shot probe so we can see Vergent's actual field names.
        if body:
            first = body[0] if isinstance(body[0], dict) else {}
            log.info("GetCustomerBanks probe cid=%s count=%s first_keys=%s",
                     cid, len(body), sorted(first.keys()))
    else:
        log.warning("GetCustomerBanks status=%s raw=%s", status, (raw or "")[:300])

    # Fallback: bank on the active loan record (LoanDetail.AccountNum).
    # Harut's loan carries this even when GetCustomerBanks returns [].
    if not shaped:
        fallback = _fallback_bank_from_loan(cid)
        if fallback:
            shaped = [fallback]

    return _json_response(200, {"banks": shaped})


def _fallback_bank_from_loan(cid: str) -> Optional[Dict[str, Any]]:
    """Pull a minimal bank record from the active loan's LoanDetail.

    We don't get a real bank id from the loan detail; use the header's
    PaymentBankAccountId (if present) as an id stand-in so the UI
    radio-group works. Server-side payment validation re-checks
    against GetCustomerBanks, so a synthetic id here only affects
    display.
    """
    status, body = _v1_get(f"/V1/{cid}/loans")
    if status != 200 or not isinstance(body, list) or not body:
        return None
    for rec in body:
        if not isinstance(rec, dict):
            continue
        detail = rec.get("LoanDetail") if isinstance(rec.get("LoanDetail"), dict) else {}
        hdr = rec.get("LoanHeader") if isinstance(rec.get("LoanHeader"), dict) else {}
        account = detail.get("AccountNum") or detail.get("accountNum")
        if not account:
            continue
        last4 = _extract_last4([account])
        if not last4:
            continue
        return {
            "id": hdr.get("PaymentBankAccountId") or detail.get("BankAccountId") or 0,
            "name": detail.get("Lender") or detail.get("BankName") or "Bank on file",
            "last4": last4,
            "accountType": "Checking",
            "isPrimary": True,
        }
    return None



def post_payment(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-payment — return a single-use Vergent customer-portal
    handoff URL pointing at the customer's payment page.

    Body: { loanId? }  (defaults to the customer's active loan)

    Response: { handoffUrl, _debug: { trail: [...] } }

    Why a handoff: server-side charging is unblocked-ably stuck.
    AuthenticateCognito returns 500 on the APIM proxy and 404 on the
    direct host; the handoff `token` field is a 36-char GUID, not a
    customer JWT (CreditCardPayment with it returns
    DependencyResolutionException, same as the service token).
    Customer-portal sign-in uses email + 2FA which can't be replicated
    from a Lambda.

    The frontend opens the URL in an iframe modal so it looks roughly
    in-portal (with a fallback "open in new tab" link if Vergent's
    X-Frame-Options blocks the iframe).
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        body = {}

    # Loan id: explicit if provided, else the customer's active loan.
    loan_id = body.get("loanId")
    if loan_id is None:
        active = _fetch_active_loan(cid)
        loan_id = active.get("id") if active else None
    if loan_id is None:
        return _json_response(400, {"error": "no_loan"})

    apim_tok = _get_apim_token()
    creds = _get_creds()
    if not (apim_tok and creds):
        return _json_response(502, {"error": "vergent_creds_missing"})

    handoff_body = {
        "customerId":               int(cid),
        # Vergent's whitelist for handoff redirects is restrictive on
        # payment subpaths. Per the docstring above + a 2026-05 test:
        #   /payment/loan/makepayment/{id}    → whitelist rejects → /error
        #   /payment/loan/paymentmethod/{id}  → whitelist rejects → /error
        # The customer-portal ROOT, however, is always allowed because
        # it's the natural post-auth landing. Send them there; they
        # land signed in on their Vergent dashboard and click
        # "Make a Payment" once to start the flow. One extra click
        # vs. a guaranteed-broken /error redirect.
        #
        # If/when Vergent whitelists a specific payment subpath for
        # us, swap this back to "/payment/loan/makepayment/{loan_id}"
        # and test (the customer's handoff will land directly on the
        # pay page).
        "TargetRelativePage":       "/",
        "ExpectedReferrerAuthority": "cashinflash.my.vergentlms.com",
    }
    handoff_headers = {
        "x-api-key":     creds["xApiKey"],
        "Authorization": f"Bearer {apim_tok}",
    }

    # Vergent's apply-portal handoff endpoint (/api/authenticate/handoff/
    # create) returns a URL on cashinflash.apply.vergentlms.com — wrong
    # portal. Try the customer-portal-scoped variants first; they may
    # return URLs on cashinflash.my.vergentlms.com.
    candidate_paths = [
        "/api/CustomerPortal/Authenticate/handoff/create",
        "/api/CustomerPortal/handoff/create",
        "/api/authenticate/handoff/create",
    ]

    trail: list = []
    handoff_url: Optional[str] = None
    fallback_url: Optional[str] = None
    for path in candidate_paths:
        url = f"{APIM_BASE}{path}"
        status, parsed, raw = _http(
            url, "POST", body=handoff_body, headers=handoff_headers,
        )
        entry = {
            "step":    "handoff",
            "via":     path,
            "status":  status,
            "rawHead": (raw or "")[:200],
        }
        trail.append(entry)
        log.info("handoff probe path=%s status=%s rawHead=%s",
                 path, status, (raw or "")[:200])
        if status == 200 and isinstance(parsed, dict):
            url_in_resp = (parsed.get("handoffUrl")
                           or parsed.get("handoff_url"))
            if url_in_resp:
                if "my.vergentlms.com" in url_in_resp:
                    handoff_url = url_in_resp
                    entry["matchedHost"] = "my"
                    break
                if not fallback_url:
                    fallback_url = url_in_resp
                    entry["matchedHost"] = "apply_fallback"

    chosen = handoff_url or fallback_url
    if not chosen:
        return _json_response(502, {
            "error":  "handoff_failed",
            "_debug": {"trail": trail},
        })

    log.info("handoff returning cid=%s loan_id=%s url_host=%s",
             cid, loan_id,
             "my" if handoff_url else "apply_fallback")
    return _json_response(200, {
        "handoffUrl": chosen,
        "loanId":     loan_id,
        "_debug":     {"trail": trail},
    })


# ─────────────────────────────────────────
# OmniaPay / Add-card config endpoint
# ─────────────────────────────────────────
def get_payment_config(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-payment-config — return the OmniaPay iframe URL for Add Card.

    Path uses /api/my-* prefix to match the existing CloudFront
    behavior pattern; otherwise CloudFront falls through to S3 and
    returns 403 XML.

    Creates a fresh OmniaPay iframe session per request so the GUID is
    short-lived and tied to this customer. The frontend embeds the
    returned iframeUrl directly; the customer enters card data inside
    the iframe (PAN never traverses our infrastructure).
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    # The referer URL has to match what OmniaPay's iframe expects for
    # X-Frame-Options / postMessage origin checks. We accept it from
    # the request's Origin header to handle dev (CloudFront) and prod
    # (portal.cashinflash.com) without redeploys.
    headers = (event.get("headers") or {})
    origin = (
        headers.get("origin")
        or headers.get("Origin")
        or "https://d1zucrj1ouu3c.cloudfront.net"
    )

    session = _create_omniapay_session(customer_id=str(cid),
                                       referer_url=origin)
    if not session:
        return _json_response(502, {
            "error": "omniapay_session_failed",
            "message": (
                "Could not create OmniaPay iframe session. "
                "Check CloudWatch logs for the probe trail."
            ),
        })

    return _json_response(200, {
        "iframeUrl": session["iframeUrl"],
        "iframeBase": OMNIAPAY_IFRAME_BASE,
    })


# ─────────────────────────────────────────
# Phase ZZ'.0 — Vergent CustomerPortal flow probe
# ─────────────────────────────────────────
# Vergent's support reply (2026-05-11) recommends:
#   1. POST /api/CustomerPortal/AuthenticateCognito {jwt: <cognito-id-token>}
#      → returns customer-scoped Vergent JWT
#   2. GET /api/CustomerPortal/Loans/{loanId}/Source/Active/PaymentSchedule
#      → returns scheduled-payment items (transactionItemId is the
#        `paymentId` for the charge endpoint)
#   3. POST /api/CustomerPortal/Loans/Payments/CreditCardPayment
#      {loanId, paymentId, amountDue, isInRescindPeriod, authCode}
#      → charges the customer's default saved card
#
# This probe exercises steps 1 + 2 ONLY (no charge) against three
# host candidates in order. Vergent points us at api-external,
# which we have never tested. Direct-invoke only.
#
# Invoke from the Lambda console Test tab with:
#   {"probe": "customerportal-flow",
#    "cognitoJwt": "<raw Cognito ID token from sessionStorage>",
#    "loanId": 4830592}
_CP_HOSTS = [
    "https://api-external.vergentlms.com",
    "https://prod.apim.vergentlms.com/external/shared",
    "https://prod.api.vergentlms.com",
]


def _probe_customerportal_flow(event: Dict[str, Any]) -> Dict[str, Any]:
    cognito_jwt = (event.get("cognitoJwt") or "").strip()
    loan_id = event.get("loanId")
    if not cognito_jwt or not loan_id:
        return {"error": "missing cognitoJwt or loanId in event"}

    creds = _get_creds() or {}
    x_api_key = creds.get("xApiKey") or ""
    if not x_api_key:
        return {"error": "no xApiKey in vergent credentials secret"}

    trail = {"auth": [], "schedule": None}

    # Step 1: try AuthenticateCognito on each host until one returns 200 + JWT.
    vergent_jwt: Optional[str] = None
    winning_host: Optional[str] = None
    for host in _CP_HOSTS:
        url = f"{host}/api/CustomerPortal/AuthenticateCognito"
        status, parsed, raw = _http(
            url, "POST",
            body={"jwt": cognito_jwt},
            headers={"x-api-key": x_api_key, "Content-Type": "application/json"},
        )
        tok = None
        if isinstance(parsed, dict):
            tok = parsed.get("token") or parsed.get("Token") or parsed.get("jwt")
        trail["auth"].append({
            "host": host,
            "status": status,
            "has_token": bool(tok),
            "jwt_prefix": (tok[:30] + "...") if tok else None,
            "raw_head": (raw or "")[:600],
        })
        log.info("[VERGENT-CP-PROBE] auth host=%s status=%s has_token=%s",
                 host, status, bool(tok))
        if status == 200 and tok:
            vergent_jwt = tok
            winning_host = host
            break

    if not vergent_jwt:
        return {"probe": "customerportal-flow", "auth_passed": False, "trail": trail}

    # Step 2: PaymentSchedule on the winning host with the new JWT.
    sched_url = (f"{winning_host}/api/CustomerPortal/Loans/"
                 f"{int(loan_id)}/Source/Active/PaymentSchedule")
    s_status, s_parsed, s_raw = _http(
        sched_url, "GET", body=None,
        headers={
            "x-api-key": x_api_key,
            "Authorization": f"Bearer {vergent_jwt}",
        },
    )
    log.info("[VERGENT-CP-PROBE] schedule host=%s loan=%s status=%s",
             winning_host, loan_id, s_status)

    # Normalize parsed shape — Vergent often wraps lists in {Items: [...]}
    items: list = []
    if isinstance(s_parsed, list):
        items = s_parsed
    elif isinstance(s_parsed, dict):
        for k in ("Items", "items", "Schedule", "schedule", "loanTransactionHistoryList"):
            v = s_parsed.get(k)
            if isinstance(v, list):
                items = v
                break

    trail["schedule"] = {
        "host": winning_host,
        "url": sched_url,
        "status": s_status,
        "raw_head": (s_raw or "")[:1500],
        "item_count": len(items),
        "first_item": items[0] if items else None,
        "last_item": items[-1] if items else None,
    }

    return {
        "probe": "customerportal-flow",
        "auth_passed": True,
        "schedule_passed": s_status == 200 and len(items) > 0,
        "winning_host": winning_host,
        "trail": trail,
    }


# ─────────────────────────────────────────
# Repay RgAPI — direct-charge endpoint (no Vergent dependency)
# ─────────────────────────────────────────
# Path 1 implementation (see prior session docstring above).
# Vergent's /V1/PostCustomerLoanPayment is broken for our tenant
# and Vergent doesn't expose the saved-card Repay token in its
# GetCustomerCards response (cardRef + cardGuid come back empty).
# So we charge the customer's card directly via Repay's modern
# REST API ("RgAPI"). Customer enters their card in our portal;
# Repay returns a transaction_id (PNRef) on success; we record
# the payment in our own DDB ledger.
#
# Endpoint docs (per Repay's Postman collection, 2026-05):
#   POST {hostname}/rgapi/v1.0/transactions/card/sale
#   Headers:
#     Content-Type:      application/json
#     rg-api-user:       gatewayApiUser    (same field that CardSafe uses)
#     rg-api-secure-token: gatewaySecureToken
#   Body:
#     amount        decimal   required — sale amount in dollars
#     card_number   string    required — PAN (we proxy from customer browser)
#     exp_date      "MMYY"    required — Repay's format
#     cvv           string    optional but recommended (lower fees, fewer declines)
#     name_on_card  string    optional but used for AVS
#     street, zip   strings   optional, used for AVS
#     customer_id   string    optional — our internal CID, helps Repay group activity
#     invoice_id    string    optional — we pass loanId here so reconciliation joins
#     card_not_present  bool  required — true (we're never card-present)
#   200 Response:
#     transaction_id  int    Repay's PNRef — store as payment proof
#     result          "0"    "0" = approved; non-zero = declined/error
#     result_text     str    "Approved" / decline reason
#     auth_amount     decimal — what was actually authorized (may be partial)
#     approval_code   str    issuer auth code
#     last4, payment_type_id — display fields for receipts
#
# Sandbox: api.sandbox.repayonline.com (test cards only, no real money)
# Prod:    api.repayonline.com         (REAL CARDS — flip via env var)
#
# PCI scope note: PAN passes through this Lambda exactly the same
# way it does in handlers/if_submit.py's CardSafe flow today —
# already SAQ A-EP. The Lambda never persists PAN; the body is
# request-scoped only. Long-term plan is Repay Hosted Fields
# (PAN goes browser→Repay directly), which would tighten back
# to SAQ A.

REPAY_API_HOSTNAME = os.environ.get(
    "REPAY_API_HOSTNAME", "api.sandbox.repayonline.com",
).rstrip("/")

# Ledger DDB table — every charge attempt logs a row here. Source
# of truth for "did this customer pay?" until/unless we get
# /V1/PostCustomerLoanPayment working for upstream reconciliation.
PAYMENT_LEDGER_TABLE = os.environ.get(
    "PAYMENT_LEDGER_TABLE", "cif-portal-payments-ledger-dev",
)

import time as _time
import uuid as _uuid


def _dynamo_client():
    """Lazy boto3 dynamodb client — only built when first charge
    request hits the Lambda (cold-start cost stays off the
    GET-only paths)."""
    import boto3
    return boto3.client(
        "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def _strip_digits(s: Any) -> str:
    """Pull only digits out of a string (PAN/zip/etc.)."""
    if not s:
        return ""
    return "".join(ch for ch in str(s) if ch.isdigit())


# ─────────────────────────────────────────
# Saved payment methods (DDB-backed)
# ─────────────────────────────────────────
# Path 1 expansion: customers save tokenized cards in OUR DDB on
# first successful charge. Future visits show a card list and
# require only CVV + amount. Vergent's GetCustomerCards is
# bypassed entirely (its cardRef/cardGuid fields come back empty
# for our tenant — see docstring earlier in this file).
#
# DDB shape: PK customerId (HASH), SK methodId (RANGE).
# Methods are scoped to a single customer; we never query
# across customers.

PAYMENT_METHODS_TABLE = os.environ.get(
    "PAYMENT_METHODS_TABLE", "cif-portal-customer-payment-methods-dev",
)

# Brand id from Vergent's enum (Visa=1, MC=2, etc.) doesn't apply
# here — the saved-cards UI shows the BIN-detected brand string
# directly.


def _cardsafe_url() -> str:
    """Return the CardSafe StoreCard endpoint, mirroring whichever
    Repay environment the rest of the Lambda is talking to (so
    sandbox creds tokenize against the sandbox host)."""
    hostname = os.environ.get("REPAY_API_HOSTNAME",
                              "api.sandbox.repayonline.com")
    return f"https://{hostname}/ws/CardSafe.asmx/StoreCard"


def _cardsafe_tokenize(*, pan_digits: str, exp_month: int, exp_year: int,
                       cvv_digits: str, name_on_card: str, zip_code: str,
                       customer_key: str) -> Tuple[Optional[str], str]:
    """Tokenize a card via Repay CardSafe StoreCard. Returns
    (token, debug). On failure token is None and debug carries a
    short diagnostic safe to log (never includes PAN or CVV).

    This is the same SOAP/ASMX endpoint handlers/if_submit.py uses
    for the Instant Funding flow, but pointed at the sandbox host
    when REPAY_API_HOSTNAME indicates sandbox. The auth is the
    same gatewayApiUser + gatewaySecureToken pair we use for
    RgAPI charges — Repay scopes both APIs to the same merchant.
    """
    creds = _get_repay_rgapi_creds()
    if not creds:
        return None, "no_creds"
    user = (creds.get("gatewayApiUser")
            or creds.get("gatewayAPIUser")
            or creds.get("gateway_api_user")
            or creds.get("apiUser") or "")
    pwd = (creds.get("gatewaySecureToken")
           or creds.get("gateway_secure_token")
           or creds.get("secureToken") or "")
    if not (user and pwd):
        return None, "creds_incomplete"

    # CardSafe expects ExpDate as MMYY (no slash, no separators).
    exp_str = f"{exp_month:02d}{str(exp_year)[-2:]}"

    from urllib.parse import urlencode
    form = urlencode({
        "UserName":    user,
        "Password":    pwd,
        "TokenMode":   "Default",
        "CardNum":     pan_digits,
        "ExpDate":     exp_str,
        "CustomerKey": str(customer_key or ""),
        "NameOnCard":  name_on_card or "",
        "Street":      "",
        "Zip":         zip_code or "",
        "ExtData":     "",
    }).encode("utf-8")

    url = _cardsafe_url()
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        url, data=form, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/xml,application/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
        log.warning("cardsafe StoreCard HTTP %s: %s", e.code, body[:300])
        return None, f"http_{e.code}"
    except Exception as exc:
        log.warning("cardsafe StoreCard error: %s", exc)
        return None, f"{type(exc).__name__}"

    # Response is a SOAP envelope OR a `<string>...</string>` wrapper
    # containing pipe-delimited fields. The first field is the token
    # when successful. Parse defensively — different Repay versions
    # have slightly different formats.
    import re
    inner = raw
    m = re.search(r"<(?:string)[^>]*>([^<]+)</string>", raw)
    if m:
        inner = m.group(1).strip()
    # Pipe-delimited: TOKEN|status|message|...
    parts = inner.split("|")
    token = parts[0].strip() if parts else ""
    # CardSafe returns "0" or empty when there's no real token — treat
    # short / numeric-only responses as a failure.
    if not token or len(token) < 8 or token.isdigit():
        log.warning("cardsafe StoreCard unexpected response: %s",
                    inner[:200])
        return None, f"bad_response:{inner[:80]}"
    log.info("cardsafe StoreCard ok customer_key=%s token_head=%s",
             customer_key, token[:8])
    return token, "ok"


def _save_payment_method(*, cid: str, repay_token: str, brand: str,
                         last4: str, exp_month: int, exp_year: int,
                         name_on_card: str) -> Optional[str]:
    """Insert a saved card row. Returns methodId on success, None
    on DDB failure (we log + return None; the charge itself
    already succeeded, so a missed save is recoverable next time
    the customer pays with the same card).
    """
    method_id = str(_uuid.uuid4())
    now = int(_time.time())
    item: Dict[str, Any] = {
        "customerId":   {"S": str(cid)},
        "methodId":     {"S": method_id},
        "repayToken":   {"S": repay_token},
        "brand":        {"S": brand or "Card"},
        "last4":        {"S": last4 or ""},
        "expMonth":     {"N": str(int(exp_month))},
        "expYear":      {"N": str(int(exp_year))},
        "nameOnCard":   {"S": (name_on_card or "")[:64]},
        "createdAt":    {"N": str(now)},
        "isDefault":    {"BOOL": True},  # first card is default
    }
    try:
        _dynamo_client().put_item(
            TableName=PAYMENT_METHODS_TABLE, Item=item,
        )
        return method_id
    except Exception as exc:
        log.warning("payment method put failed cid=%s: %s", cid, exc)
        return None


def _list_payment_methods(cid: str) -> List[Dict[str, Any]]:
    """Return all saved cards for the customer, newest first."""
    try:
        resp = _dynamo_client().query(
            TableName=PAYMENT_METHODS_TABLE,
            KeyConditionExpression="customerId = :c",
            ExpressionAttributeValues={":c": {"S": str(cid)}},
        )
    except Exception as exc:
        log.warning("payment methods list failed cid=%s: %s", cid, exc)
        return []
    rows = []
    for item in resp.get("Items") or []:
        rows.append({
            "methodId":   item.get("methodId", {}).get("S"),
            "brand":      item.get("brand", {}).get("S") or "Card",
            "last4":      item.get("last4", {}).get("S") or "",
            "expMonth":   int(item.get("expMonth", {}).get("N", "0") or 0),
            "expYear":    int(item.get("expYear", {}).get("N", "0") or 0),
            "nameOnCard": item.get("nameOnCard", {}).get("S") or "",
            "createdAt":  int(item.get("createdAt", {}).get("N", "0") or 0),
            "isDefault":  bool(item.get("isDefault", {}).get("BOOL")),
        })
    rows.sort(key=lambda r: r.get("createdAt", 0), reverse=True)
    return rows


def _get_payment_method(cid: str,
                         method_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one saved card (including the repayToken — only
    used server-side for charging, never returned to the
    frontend)."""
    if not method_id:
        return None
    try:
        resp = _dynamo_client().get_item(
            TableName=PAYMENT_METHODS_TABLE,
            Key={"customerId": {"S": str(cid)},
                 "methodId":   {"S": str(method_id)}},
        )
    except Exception as exc:
        log.warning("payment method get failed cid=%s mid=%s: %s",
                    cid, method_id, exc)
        return None
    item = resp.get("Item") or {}
    if not item:
        return None
    return {
        "methodId":   item.get("methodId", {}).get("S"),
        "repayToken": item.get("repayToken", {}).get("S"),
        "brand":      item.get("brand", {}).get("S") or "Card",
        "last4":      item.get("last4", {}).get("S") or "",
        "expMonth":   int(item.get("expMonth", {}).get("N", "0") or 0),
        "expYear":    int(item.get("expYear", {}).get("N", "0") or 0),
        "nameOnCard": item.get("nameOnCard", {}).get("S") or "",
    }


def _delete_payment_method(cid: str, method_id: str) -> bool:
    try:
        _dynamo_client().delete_item(
            TableName=PAYMENT_METHODS_TABLE,
            Key={"customerId": {"S": str(cid)},
                 "methodId":   {"S": str(method_id)}},
        )
        return True
    except Exception as exc:
        log.warning("payment method delete failed cid=%s mid=%s: %s",
                    cid, method_id, exc)
        return False


def get_my_payment_methods(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-payment-methods — list saved cards for the
    signed-in customer (token + sensitive fields stripped)."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})
    methods = _list_payment_methods(cid)
    # repayToken is server-only; the list helper already omits it.
    return _json_response(200, {"methods": methods})


def delete_my_payment_method(event: Dict[str, Any],
                              method_id: str) -> Dict[str, Any]:
    """DELETE /api/my-payment-methods/{methodId}"""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})
    if not method_id:
        return _json_response(400, {"error": "missing_method_id"})
    ok = _delete_payment_method(cid, method_id)
    if not ok:
        return _json_response(502, {"error": "delete_failed"})
    return _json_response(200, {"ok": True})


def _record_payment_ledger(
    *, cid: str, loan_id: Any, amount: float, result: str,
    transaction_id: Optional[Any], result_text: str, last4: str,
    error_detail: Optional[str] = None,
) -> Optional[str]:
    """Write a payment-attempt row to DDB. Returns the row's
    ledgerId on success, None on failure (failure is logged but
    does NOT block the response — the customer's charge already
    succeeded with Repay; losing the audit row is recoverable
    via Repay's reporting if we have transaction_id).
    """
    ledger_id = str(_uuid.uuid4())
    now = int(_time.time())
    item: Dict[str, Any] = {
        "ledgerId":      {"S": ledger_id},
        "customerId":    {"S": str(cid)},
        "loanId":        {"S": str(loan_id) if loan_id is not None else ""},
        "amount":        {"N": f"{float(amount):.2f}"},
        "result":        {"S": str(result)},
        "resultText":    {"S": str(result_text or "")},
        "last4":         {"S": str(last4 or "")},
        "createdAt":     {"N": str(now)},
        "processor":     {"S": "repay-rgapi"},
        # Lifecycle: charged → vergent_recorded | vergent_failed |
        # manual_reconcile. Defaults to "charged" until the Vergent
        # POST round-trips (next commit).
        "reconcileState": {"S": "charged" if result == "0" else "declined"},
    }
    if transaction_id is not None:
        item["transactionId"] = {"S": str(transaction_id)}
    if error_detail:
        item["errorDetail"] = {"S": error_detail[:500]}
    try:
        _dynamo_client().put_item(
            TableName=PAYMENT_LEDGER_TABLE, Item=item,
        )
        return ledger_id
    except Exception as exc:
        log.warning("payment ledger put failed cid=%s txn=%s: %s",
                    cid, transaction_id, exc)
        return None


def _update_ledger_reconcile(*, ledger_id: str, state: str,
                              vergent_payment_id: Optional[str] = None,
                              detail: Optional[str] = None) -> None:
    """Patch a ledger row's reconcileState after Vergent post.
    Best-effort: a failed update is logged, not propagated."""
    if not ledger_id:
        return
    expr = "SET reconcileState = :s"
    vals: Dict[str, Any] = {":s": {"S": state}}
    if vergent_payment_id:
        expr += ", vergentPaymentId = :v"
        vals[":v"] = {"S": str(vergent_payment_id)}
    if detail:
        expr += ", reconcileDetail = :d"
        vals[":d"] = {"S": detail[:500]}
    try:
        _dynamo_client().update_item(
            TableName=PAYMENT_LEDGER_TABLE,
            Key={"ledgerId": {"S": ledger_id}},
            UpdateExpression=expr,
            ExpressionAttributeValues=vals,
        )
    except Exception as exc:
        log.warning("ledger reconcile update failed lid=%s: %s",
                    ledger_id, exc)


def _post_payment_to_vergent(*, cid: str, loan_id: Any, amount: float,
                              transaction_id: Any, last4: str,
                              brand: str, approval_code: str,
                              repay_token: Optional[str]) -> Tuple[bool, str, Optional[str]]:
    """Tell Vergent's V1 admin API that a payment was processed,
    so their loan balance reflects it.

    Returns (success, detail, vergent_payment_id).

    Body shape is modeled on the working
    /V1/PostCustomerCardTokenized call in handlers/if_submit.py —
    same V1 surface, same service-token auth, same snake_case
    convention. The previous /V1/PostCustomerLoanPayment attempt
    documented at the top of this file 500'd with
    NullReferenceException, likely because the body was missing
    fields we now know are required (company_id, processor,
    transaction_id from a real Repay charge, etc.). If this
    still fails for our tenant, the DDB ledger flags the row
    as needing manual reconciliation; staff can apply the
    payment in Vergent's admin UI from a future admin-only view.
    """
    if not transaction_id:
        return False, "no_transaction_id", None
    try:
        cid_int = int(cid)
        loan_id_int = int(loan_id) if loan_id is not None else 0
    except (TypeError, ValueError):
        return False, "bad_ids", None

    amount_dollars = round(float(amount), 2)
    body = {
        # PascalCase (the form this endpoint actually wants).
        # Vergent's DTO treats "Id" as the loan id (its primary
        # entity under modification), NOT a "new record" sentinel
        # like /V1/PostCustomerCardTokenized's "id": 0. Confirmed
        # 2026-05-14 by their 500:
        #   "No Loan record found for 0"
        #   System.IndexOutOfRangeException
        #   Vergent.Common.Lib.Converted.Loan.LoanDataObj.get_LoanDr()
        # So Id ← loan_id, not 0. LoanId stays too (belt + suspenders).
        "Id":                loan_id_int,
        "CompanyId":         VERGENT_COMPANY_ID,
        "CustomerId":        cid_int,
        "LoanId":            loan_id_int,
        "PaymentAmount":     amount_dollars,
        "PaymentDate":       None,  # let Vergent default to now
        "PaymentTypeId":     1,
        "PaymentMethodId":   1,
        "TransactionId":     str(transaction_id),
        "ApprovalCode":      approval_code or "",
        "CardRef":           repay_token or "",
        "CardLastFour":      last4 or "",
        "Processor":         "Repay",
        "IsProcessed":       True,
        "IsSettled":         False,
        "FromCustomerPortal": True,
        "Notes":             "Customer portal payment via cif-portal",

        # snake_case fallback duplicates — harmless if ignored.
        "id":                loan_id_int,
        "company_id":        VERGENT_COMPANY_ID,
        "customer_id":       cid_int,
        "loan_id":           loan_id_int,
        "amount":            amount_dollars,
        "transaction_id":    str(transaction_id),
        "card_ref":          repay_token or "",
        "card_last_four":    last4 or "",
        "approval_code":     approval_code or "",
        "processor":         "Repay",
        "payment_type_id":   1,
        "payment_method_id": 1,
        "is_processed":      True,
        "is_settled":        False,
        "from_customer_portal": True,
    }
    log.info("vergent reconcile cid=%s loan=%s amt=%s repay_txn=%s",
             cid, loan_id, amount, transaction_id)
    status, resp, raw = _v1_request(
        "POST", "/V1/PostCustomerLoanPayment", body=body,
    )
    head = (raw or "")[:300]
    log.info("vergent reconcile response status=%s body_head=%s",
             status, head)

    if status in (200, 201) and isinstance(resp, dict):
        vergent_payment_id = (resp.get("id") or resp.get("paymentId")
                              or resp.get("PaymentId"))
        return True, "ok", (str(vergent_payment_id) if vergent_payment_id else None)
    return False, f"http_{status}:{head[:200]}", None


def post_charge(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-payment/charge

    Two body shapes accepted:

    A) New card (auto-saves on first successful charge):
        amount       (number, required)
        cardNumber   (string, required) — full PAN
        expMonth     (number, required)
        expYear      (number, required) — 4- or 2-digit
        cvv          (string, optional but recommended)
        nameOnCard   (string, optional)
        zip          (string, optional)
        loanId       (number, optional)

    B) Saved card (re-use a previously-tokenized card):
        amount           (number, required)
        paymentMethodId  (string, required) — DDB key
        cvv              (string, optional but recommended)
        loanId           (number, optional)

    On success the response includes:
        success         bool
        transactionId   int   — Repay PNRef
        authAmount      number
        approvalCode    string
        last4, brand    strings
        resultText      string
        ledgerId        string  — our DDB row id
        savedMethodId   string  — populated when a new card was
                                  auto-saved; null when paying
                                  with an existing saved card.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "invalid_json"})
    if not isinstance(body, dict):
        return _json_response(400, {"error": "invalid_body"})

    # ── Amount validation (shared by both flows) ──
    try:
        amount = float(body.get("amount") or 0)
    except (TypeError, ValueError):
        return _json_response(400, {"error": "invalid_amount"})
    if amount <= 0 or amount > 5000:
        # Cap at $5k — Repay supports much higher but our portal
        # has no use case beyond a single-loan paydown.
        return _json_response(400, {"error": "amount_out_of_range"})

    cvv = (body.get("cvv") or "").strip()
    cvv_digits = _strip_digits(cvv)
    if cvv and (len(cvv_digits) < 3 or len(cvv_digits) > 4):
        return _json_response(400, {"error": "invalid_cvv"})

    # Resolve loan: explicit if provided, else active loan.
    loan_id = body.get("loanId")
    if loan_id is None:
        active = _fetch_active_loan(cid)
        loan_id = active.get("id") if active else None

    # ── Auth to Repay (shared) ──
    creds = _get_repay_rgapi_creds()
    if not creds:
        return _json_response(502, {"error": "repay_creds_missing"})
    api_user = (
        creds.get("gatewayApiUser")
        or creds.get("gatewayAPIUser")
        or creds.get("gateway_api_user")
        or creds.get("apiUser")
        or ""
    )
    api_token = (
        creds.get("gatewaySecureToken")
        or creds.get("gateway_secure_token")
        or creds.get("secureToken")
        or ""
    )
    if not (api_user and api_token):
        return _json_response(502, {"error": "repay_creds_incomplete"})

    # ── Branch on payment-method type ──
    payment_method_id = (body.get("paymentMethodId") or "").strip()
    saved_method: Optional[Dict[str, Any]] = None
    pan_digits = ""
    exp_month = 0
    exp_year = 0
    name_on_card = ""
    zip_code = ""
    using_saved = False

    if payment_method_id:
        # Saved-card flow — look up the token in DDB, charge with
        # card_token. PAN never enters the Lambda.
        saved_method = _get_payment_method(cid, payment_method_id)
        if not saved_method:
            return _json_response(404, {"error": "payment_method_not_found"})
        using_saved = True
        last4 = saved_method.get("last4") or ""
        brand = saved_method.get("brand") or "Card"
        name_on_card = saved_method.get("nameOnCard") or "Cardholder"
        exp_month = int(saved_method.get("expMonth") or 0)
        exp_year = int(saved_method.get("expYear") or 0)
    else:
        # New-card flow — validate full PAN + expiry, auto-tokenize
        # on successful charge.
        pan_digits = _strip_digits(body.get("cardNumber"))
        if len(pan_digits) < 13 or len(pan_digits) > 19:
            return _json_response(400, {"error": "invalid_card_number"})
        if not _luhn_ok(pan_digits):
            return _json_response(400, {"error": "card_failed_luhn"})

        try:
            exp_month = int(body.get("expMonth") or 0)
            exp_year = int(body.get("expYear") or 0)
        except (TypeError, ValueError):
            return _json_response(400, {"error": "invalid_expiry"})
        if not (1 <= exp_month <= 12):
            return _json_response(400, {"error": "invalid_exp_month"})
        if exp_year < 100:
            exp_year += 2000
        if exp_year < 2026 or exp_year > 2050:
            return _json_response(400, {"error": "invalid_exp_year"})

        name_on_card = (body.get("nameOnCard") or "").strip()[:64]
        zip_code = _strip_digits(body.get("zip"))[:5]
        last4 = pan_digits[-4:]
        brand = _detect_card_type(pan_digits)

    exp_str = f"{exp_month:02d}{str(exp_year)[-2:]}"

    # ── Build the Repay Card Sale body ──
    sale_url = f"https://{REPAY_API_HOSTNAME}/rgapi/v1.0/transactions/card/sale"
    sale_body: Dict[str, Any] = {
        "amount":           round(amount, 2),
        "exp_date":         exp_str,
        "name_on_card":     name_on_card or "Cardholder",
        "zip":              zip_code,
        "customer_id":      str(cid),
        "invoice_id":       str(loan_id) if loan_id is not None else "",
        "card_not_present": True,
        # In sandbox: override Repay's velocity / duplicate-charge
        # protection so we can iterate freely with the same card +
        # amount during testing. In prod: keep the protection on
        # (default false) so accidental double-clicks don't
        # double-charge customers.
        "force_duplicate":  "sandbox" in REPAY_API_HOSTNAME.lower(),
        "custom_fields":    [],
    }
    if using_saved:
        sale_body["card_token"] = saved_method.get("repayToken") or ""
    else:
        sale_body["card_number"] = pan_digits
    if cvv_digits:
        sale_body["cvv"] = cvv_digits
        sale_body["cvv_mode"] = "submitted"
    else:
        sale_body["cvv_mode"] = "notsubmitted"

    sale_headers = {
        "Content-Type":        "application/json",
        "rg-api-user":         api_user,
        "rg-api-secure-token": api_token,
    }
    log.info("repay charge cid=%s loan=%s amt=%s last4=%s",
             cid, loan_id, amount, last4)
    status, parsed, raw = _http(
        sale_url, "POST", body=sale_body, headers=sale_headers, timeout=30,
    )
    # Strip PAN/CVV from anything we log or echo back, defense in depth.
    log_safe_body = dict(sale_body)
    log_safe_body["card_number"] = f"****{last4}"
    log_safe_body.pop("cvv", None)
    log.info("repay charge response cid=%s status=%s body_head=%s",
             cid, status, (raw or "")[:300])

    if not isinstance(parsed, dict):
        ledger_id = _record_payment_ledger(
            cid=cid, loan_id=loan_id, amount=amount, result="-1",
            transaction_id=None, result_text=f"http_{status}",
            last4=last4,
            error_detail=f"non-json upstream status={status}",
        )
        return _json_response(502, {
            "success":   False,
            "error":     "repay_http_error",
            "_status":   status,
            "ledgerId":  ledger_id,
        })

    result = str(parsed.get("result") or "")
    result_text = parsed.get("result_text") or parsed.get("response_message", {}).get("description") or ""
    transaction_id = parsed.get("transaction_id")
    auth_amount = parsed.get("auth_amount") or parsed.get("total_amount") or 0
    approval_code = parsed.get("approval_code") or ""

    ledger_id = _record_payment_ledger(
        cid=cid, loan_id=loan_id, amount=float(auth_amount or amount),
        result=result, transaction_id=transaction_id,
        result_text=result_text, last4=last4,
    )

    if result == "0" and transaction_id:
        # Auto-save tokenized card on first successful charge.
        # Only for new-card flow — saved-card flow already has the
        # token. Tokenization failure does NOT fail the response
        # (the customer's money already moved); we just log and
        # continue. They'll re-enter their card next time.
        saved_method_id = None
        if not using_saved and pan_digits:
            try:
                token, debug = _cardsafe_tokenize(
                    pan_digits=pan_digits,
                    exp_month=exp_month,
                    exp_year=exp_year,
                    cvv_digits=cvv_digits,
                    name_on_card=name_on_card,
                    zip_code=zip_code,
                    customer_key=str(cid),
                )
                if token:
                    saved_method_id = _save_payment_method(
                        cid=cid, repay_token=token, brand=brand,
                        last4=last4, exp_month=exp_month, exp_year=exp_year,
                        name_on_card=name_on_card,
                    )
                else:
                    log.info("cardsafe tokenize skipped/failed cid=%s: %s",
                             cid, debug)
            except Exception as exc:
                # Belt-and-suspenders — should never throw given the
                # helper catches its own errors, but the customer's
                # charge already succeeded so we MUST return success.
                log.warning("auto-save tokenize unexpected error cid=%s: %s",
                            cid, exc)

        # ── Vergent reconciliation (best-effort) ──
        # Tell Vergent's V1 admin API the payment landed so the
        # customer's loan balance reflects it on their next refresh.
        # Failure does NOT change the response — the customer's
        # money already moved through Repay, and our DDB ledger
        # row marks the row "vergent_failed" so staff can apply
        # it manually from the future admin reconciliation view.
        vergent_status = "vergent_pending"
        try:
            ok, detail, vergent_pid = _post_payment_to_vergent(
                cid=cid, loan_id=loan_id, amount=float(auth_amount or amount),
                transaction_id=transaction_id, last4=last4, brand=brand,
                approval_code=approval_code,
                repay_token=(
                    (saved_method or {}).get("repayToken") if using_saved
                    else None
                ),
            )
            if ok:
                _update_ledger_reconcile(
                    ledger_id=ledger_id, state="vergent_recorded",
                    vergent_payment_id=vergent_pid,
                )
                vergent_status = "vergent_recorded"
            else:
                _update_ledger_reconcile(
                    ledger_id=ledger_id, state="vergent_failed",
                    detail=detail,
                )
                vergent_status = "vergent_failed"
        except Exception as exc:
            log.warning("vergent reconcile unexpected error cid=%s: %s",
                        cid, exc)
            _update_ledger_reconcile(
                ledger_id=ledger_id, state="vergent_failed",
                detail=f"exception:{type(exc).__name__}",
            )
            vergent_status = "vergent_failed"

        return _json_response(200, {
            "success":       True,
            "transactionId": transaction_id,
            "authAmount":    auth_amount,
            "approvalCode":  approval_code,
            "last4":         last4,
            "brand":         brand,
            "resultText":    result_text or "Approved",
            "ledgerId":      ledger_id,
            "savedMethodId": saved_method_id,
            "usedSavedCard": using_saved,
            "vergentReconcile": vergent_status,
        })

    # Declined / error.
    return _json_response(200, {
        "success":     False,
        "result":      result,
        "resultText":  result_text or "Declined",
        "last4":       last4,
        "brand":       brand,
        "ledgerId":    ledger_id,
    })


# Cache for the RgAPI creds (same Secrets Manager secret CardSafe
# uses — gatewayApiUser/gatewaySecureToken values are shared
# across CardSafe and RgAPI per Repay's account model).
# Two separate secrets — production and sandbox creds aren't
# interchangeable (Repay returns 404 "User not found" if a prod
# user hits the sandbox host or vice-versa). The hostname env
# var drives which secret we read.
_repay_rgapi_creds_cache: Optional[Dict[str, Any]] = None
_repay_rgapi_creds_cache_env: Optional[str] = None


def _get_repay_rgapi_creds() -> Optional[Dict[str, Any]]:
    """Return Repay RgAPI creds dict {gatewayApiUser,
    gatewaySecureToken, ...}. Picks the sandbox secret when
    REPAY_API_HOSTNAME contains 'sandbox', else the production
    secret. Cache is keyed on the choice so toggling hostnames
    via env var (no code change) immediately reads the right
    secret on the next cold start.
    """
    global _repay_rgapi_creds_cache, _repay_rgapi_creds_cache_env
    hostname = os.environ.get("REPAY_API_HOSTNAME", "")
    is_sandbox = "sandbox" in hostname.lower()
    env = "sandbox" if is_sandbox else "prod"

    if _repay_rgapi_creds_cache is not None and _repay_rgapi_creds_cache_env == env:
        return _repay_rgapi_creds_cache

    if is_sandbox:
        arn = os.environ.get(
            "REPAY_SANDBOX_SECRET_ARN",
            "cif-portal/repay/sandbox-credentials",
        )
    else:
        arn = os.environ.get(
            "REPAY_SECRET_ARN", "cif-portal/repay/credentials",
        )
    try:
        resp = _secrets.get_secret_value(SecretId=arn)
        _repay_rgapi_creds_cache = json.loads(resp["SecretString"])
        _repay_rgapi_creds_cache_env = env
        log.info("repay rgapi creds loaded env=%s arn=%s", env, arn[-30:])
        return _repay_rgapi_creds_cache
    except Exception as exc:
        log.warning("repay rgapi creds read failed env=%s arn=%s: %s",
                    env, arn, exc)
        return None


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    # Unconditional one-line breadcrumb at request entry so a
    # CloudWatch tail always shows that the handler reached the
    # body even if downstream code raises. Prior debugging hit a
    # case where API Gateway's default 500 body fired with NO
    # corresponding log line in the payments Lambda's log group —
    # this print() makes that scenario distinguishable from "Lambda
    # crashed before any code ran" (import error / handler-init).
    http_for_log = (event.get("requestContext") or {}).get("http") or {}
    print(f"[payments] entry path={http_for_log.get('path')!r} "
          f"method={http_for_log.get('method')!r}")
    try:
        # Direct-invoke probe path (no API Gateway, no CORS).
        if event.get("probe") == "customerportal-flow":
            return _probe_customerportal_flow(event)

        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        path = http.get("path") or event.get("rawPath") or ""

        # Impersonation write-block: block POST/PUT/DELETE when the
        # caller is acting as another customer via an
        # X-Impersonation-Token header. See handlers/impersonation.py.
        from handlers import impersonation
        blocked = impersonation.maybe_block_write(
            event, impersonation.claims_with_impersonation(event))
        if blocked:
            return blocked

        if path.endswith("/my-cards") and method == "GET":
            return get_my_cards(event)
        if path.endswith("/my-cards") and method == "POST":
            return post_card(event)
        if path.endswith("/my-banks") and method == "GET":
            return get_my_banks(event)
        if path.endswith("/my-payment/loan-summary") and method == "GET":
            return get_loan_summary(event)
        if path.endswith("/my-payment/charge") and method == "POST":
            return post_charge(event)
        if path.endswith("/my-payment-methods") and method == "GET":
            return get_my_payment_methods(event)
        # /api/my-payment-methods/{methodId}
        if "/my-payment-methods/" in path and method == "DELETE":
            parts = [p for p in path.split("/") if p]
            method_id = parts[-1] if parts else ""
            return delete_my_payment_method(event, method_id)
        if path.endswith("/my-payment") and method == "POST":
            return post_payment(event)
        if path.endswith("/my-payment-config") and method == "GET":
            return get_payment_config(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("payments handler unexpected error: %s", exc)
        return _json_response(500, {"error": "internal_error"})
