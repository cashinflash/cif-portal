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
from typing import Any, Dict, Optional

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
        "TargetRelativePage":       f"/payment/loan/paymentsummary/{loan_id}",
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
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    try:
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        path = http.get("path") or event.get("rawPath") or ""

        if path.endswith("/my-cards") and method == "GET":
            return get_my_cards(event)
        if path.endswith("/my-cards") and method == "POST":
            return post_card(event)
        if path.endswith("/my-banks") and method == "GET":
            return get_my_banks(event)
        if path.endswith("/my-payment/loan-summary") and method == "GET":
            return get_loan_summary(event)
        if path.endswith("/my-payment") and method == "POST":
            return post_payment(event)
        if path.endswith("/my-payment-config") and method == "GET":
            return get_payment_config(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("payments handler unexpected error: %s", exc)
        return _json_response(500, {"error": "internal_error"})
