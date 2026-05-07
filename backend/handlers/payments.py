"""
Customer Portal — Payments handler (Vergent v2 APIM + Repay).

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-cards                 -> list the customer's saved cards
  GET  /api/my-payment/loan-summary  -> active loan data formatted for the pay page
  POST /api/my-payment               -> charge a saved card and post to the loan

Auth model:
  - API Gateway's Cognito JWT authorizer identifies the customer
    (custom:vergentCustomerId claim).
  - Vergent is called with the SERVICE APIM token (JWT from
    /api/authenticate at the APIM host) plus the x-api-key header.
    We reuse the exact caching pattern from loans.py::_get_apim_token.
  - Before we execute a charge, we pull the customer's loans via v1
    and confirm the requested loanId belongs to the caller. We also
    confirm cardId is in the caller's card list. Never trust the body
    alone for authorization.

PCI posture: we never touch raw PAN. Vergent returns tokenized saved
cards (last4 only); Vergent routes the charge to Repay server-side.
Our logs record cardId + last4 + amount + confirmation id.

Environment:
  VERGENT_APIM_BASE_URL  default https://prod.apim.vergentlms.com/external/shared
  VERGENT_V1_BASE_URL    default https://shared.vergentlms.com/api/api
  VERGENT_SECRET_ARN     Secrets Manager ARN (same secret as loans.py)
"""
from __future__ import annotations

import base64
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
REPAY_SECRET_ARN = os.environ.get("REPAY_SECRET_ARN",
                                  "cif-portal/repay/credentials")
REPAY_GATEWAY_BASE = os.environ.get("REPAY_GATEWAY_BASE",
                                    "https://api.repayonline.com/rgapi/v1.0")

# OmniaPay (Vergent-owned) — used for the customer-self-service Add Card
# flow via embedded iframe. Server-to-server: Lambda calls this API to
# create an iframe session, gets back a 32-char hex GUID, and the
# frontend embeds https://iframe.omniapay.com/{guid}?refererUrls=... so
# the customer's PAN/CVV never traverses our infrastructure (PCI SAQ A).
OMNIAPAY_SECRET_ARN = os.environ.get("OMNIAPAY_SECRET_ARN",
                                     "cif-portal/omniapay/credentials")
OMNIAPAY_API_BASE = os.environ.get("OMNIAPAY_API_BASE",
                                   "https://api.omniapay.com")
OMNIAPAY_IFRAME_BASE = os.environ.get("OMNIAPAY_IFRAME_BASE",
                                      "https://iframe.omniapay.com")

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
# Vergent v2 CustomerPortal — customer-context auth + payment
# ─────────────────────────────────────────
# v2 CreditCardPayment uses the loan's default funding method
# (no cardId in the request) — sidesteps v1 PostCustomerLoanPayment's
# server-side NullReferenceException when a card record lacks a
# Repay token. Auth is a v2 customer session token obtained by
# exchanging the customer's Cognito JWT via AuthenticateCognito.

def _get_customer_v2_token(event: Dict[str, Any],
                           trail: Optional[list] = None) -> Optional[str]:
    """Exchange the request's Cognito JWT for a Vergent v2 customer token.

    The customer's Cognito ID token is in the request's Authorization
    header (already validated by API Gateway's Cognito authorizer).
    Send it to v2 AuthenticateCognito to get back a Vergent customer
    session token usable for v2 CustomerPortal endpoints.

    Returns the token string, or None if the exchange fails. If
    `trail` is provided, append a step-result dict for diagnosis.
    """
    def _record(step_outcome: Dict[str, Any]) -> None:
        if trail is not None:
            trail.append(step_outcome)

    headers = event.get("headers") or {}
    auth_header = ""
    for k in ("authorization", "Authorization"):
        if k in headers and headers[k]:
            auth_header = headers[k]
            break
    jwt = auth_header.replace("Bearer ", "").replace("bearer ", "").strip()
    if not jwt:
        log.warning("v2 token exchange: no Authorization header on request")
        _record({"step": "auth", "status": 0, "note": "no_auth_header"})
        return None

    creds = _get_creds()
    if not creds:
        log.warning("v2 token exchange: vergent creds not loaded")
        _record({"step": "auth", "status": 0, "note": "no_creds"})
        return None
    api_key = creds.get("xApiKey", "")

    url = f"{APIM_BASE}/api/CustomerPortal/AuthenticateCognito"
    body = {"jwt": jwt}
    h = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    status, parsed, raw = _http(url, "POST", body=body, headers=h)
    if status != 200 or not isinstance(parsed, dict):
        log.warning("v2 AuthenticateCognito failed: status=%s raw=%s",
                    status, (raw or "")[:300])
        _record({
            "step": "auth",
            "status": status,
            "rawHead": (raw or "")[:200],
        })
        return None
    tok = parsed.get("token")
    if isinstance(tok, str) and tok.strip():
        log.info("v2 AuthenticateCognito ok: token_len=%d", len(tok))
        _record({
            "step": "auth", "status": 200, "tokenLen": len(tok.strip()),
        })
        return tok.strip()
    log.warning("v2 AuthenticateCognito returned no token: %r", parsed)
    _record({
        "step": "auth", "status": 200, "note": "no_token_in_response",
        "responseKeys": sorted(parsed.keys()),
    })
    return None


def _get_next_payment_id(loan_id: int,
                         trail: Optional[list] = None) -> Optional[int]:
    """Fetch the next scheduled payment's id for a loan via v2.

    Uses the service APIM token (same as _apim_call) since the
    customer-JWT path through AuthenticateCognito is broken for our
    tenant. `source` query param is undocumented; probe a few common
    values until one returns a parseable schedule.
    """
    tok = _get_apim_token()
    if not tok:
        if trail is not None:
            trail.append({"step": "schedule", "status": 0, "note": "no_apim_token"})
        return None
    creds = _get_creds()
    api_key = creds.get("xApiKey", "") if creds else ""
    h = {
        "x-api-key": api_key,
        "Authorization": f"Bearer {tok}",
    }
    probe_results = []
    for source in ("loan", "Loan", "1", "customer", "Customer"):
        url = (
            f"{APIM_BASE}/api/CustomerPortal/Loans/{loan_id}/"
            f"Source/{source}/PaymentSchedule"
        )
        status, parsed, raw = _http(url, "GET", headers=h)
        log.info("v2 PaymentSchedule probe loan=%s source=%s status=%s",
                 loan_id, source, status)
        probe_results.append({
            "source": source,
            "status": status,
            "rawHead": (raw or "")[:120],
        })
        if status != 200:
            continue

        def _scan(items):
            for item in items:
                if not isinstance(item, dict):
                    continue
                pid = (
                    item.get("id") or item.get("Id")
                    or item.get("paymentId") or item.get("PaymentId")
                )
                if pid:
                    try:
                        return int(pid)
                    except (TypeError, ValueError):
                        continue
            return None

        if isinstance(parsed, list):
            pid = _scan(parsed)
            if pid:
                log.info("v2 PaymentSchedule found paymentId=%s via %s",
                         pid, source)
                if trail is not None:
                    trail.append({
                        "step": "schedule", "status": 200,
                        "source": source, "paymentId": pid,
                        "probes": probe_results,
                    })
                return pid
        elif isinstance(parsed, dict):
            for key in ("payments", "Payments", "schedule", "Schedule",
                        "items", "Items", "data", "Data"):
                inner = parsed.get(key)
                if isinstance(inner, list):
                    pid = _scan(inner)
                    if pid:
                        log.info("v2 PaymentSchedule found paymentId=%s "
                                 "via %s.%s", pid, source, key)
                        if trail is not None:
                            trail.append({
                                "step": "schedule", "status": 200,
                                "source": source, "paymentId": pid,
                                "wrapKey": key, "probes": probe_results,
                            })
                        return pid
    log.warning("v2 PaymentSchedule: no paymentId found across all "
                "probed sources for loan=%s", loan_id)
    if trail is not None:
        trail.append({
            "step": "schedule", "status": 0, "note": "no_paymentId",
            "probes": probe_results,
        })
    return None


def _v2_credit_card_payment_with_customer_token(
    customer_token: str,
    loan_id: int,
    payment_id: int,
    amount: float,
    card_id: int,
    customer_id: Optional[int] = None,
) -> tuple:
    """POST /api/CustomerPortal/Loans/Payments/CreditCardPayment using the
    customer's Vergent portal token (obtained via /api/CustomerPortal/
    AuthenticateCognito).

    This is the (Auth)-annotated path documented in v2 swagger. Earlier
    attempts using the service APIM token returned DependencyResolutionException —
    likely because the endpoint's DI graph expects a customer-scoped
    auth context. Using the customer JWT exchange flow gives us that.

    Returns (status, parsed_body, raw_text). On 200, parsed_body is
    expected to be `{ success: true, scheduleDate: "..." }`.
    """
    creds = _get_creds()
    api_key = creds.get("xApiKey", "") if creds else ""
    cid_int = int(card_id)
    url = (
        f"{APIM_BASE}/api/CustomerPortal/Loans/Payments/CreditCardPayment"
        f"?cardId={cid_int}&CardId={cid_int}"
    )
    body = {
        # Documented schema fields:
        "loanId":            int(loan_id),
        "paymentId":         int(payment_id),
        "amountDue":         float(amount),
        "isInRescindPeriod": False,
        "authCode":          "",
        # cardId not in published schema but observed required at runtime —
        # send in body + query string just in case (model binder picks one).
        "cardId":            cid_int,
        "CardId":            cid_int,
    }
    if customer_id is not None:
        body["customerId"] = int(customer_id)
    h = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "Authorization": f"Bearer {customer_token}",
    }
    return _http(url, "POST", body=body, headers=h)


def _v2_credit_card_payment(loan_id: int,
                            payment_id: int,
                            amount: float,
                            card_id: int,
                            customer_id: Optional[int] = None) -> tuple:
    """POST /api/CustomerPortal/Loans/Payments/CreditCardPayment.

    Uses the service APIM token (same as _apim_call) — Vergent's
    customer-JWT auth (AuthenticateCognito) is broken for our tenant
    so we use the service-token route.

    NOTE: the published swagger schema for CreditCardPaymentRequestModel
    omits `cardId`, but Vergent's actual endpoint rejects requests
    without it ("cardId must be a non-default value"). Confirmed
    empirically against our tenant — adjust here if Vergent updates
    their schema. Field naming convention is also undocumented; we
    send the cardId in every plausible location (camelCase + Pascal
    in body, plus URL query-string) so whichever location Vergent's
    model binder reads from gets a non-default value.

    Returns (status, parsed_body, raw_text). On 200, parsed_body is
    expected to be `{ success: true, scheduleDate: "..." }`.
    """
    tok = _get_apim_token()
    if not tok:
        return 0, None, ""
    creds = _get_creds()
    api_key = creds.get("xApiKey", "") if creds else ""
    cid_int = int(card_id)
    url = (
        f"{APIM_BASE}/api/CustomerPortal/Loans/Payments/CreditCardPayment"
        f"?cardId={cid_int}&CardId={cid_int}"
    )
    body = {
        "loanId": int(loan_id),
        "LoanId": int(loan_id),
        "paymentId": int(payment_id),
        "PaymentId": int(payment_id),
        "amountDue": float(amount),
        "AmountDue": float(amount),
        "isInRescindPeriod": False,
        "IsInRescindPeriod": False,
        "cardId": cid_int,
        "CardId": cid_int,
        "card_id": cid_int,
    }
    if customer_id is not None:
        body["customerId"] = int(customer_id)
        body["CustomerId"] = int(customer_id)
    h = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "Authorization": f"Bearer {tok}",
    }
    return _http(url, "POST", body=body, headers=h)


# ─────────────────────────────────────────
# Repay RGAPI (card tokenization)
# ─────────────────────────────────────────
_repay_creds_cache: Optional[Dict[str, str]] = None
# The first call probes a handful of likely tokenize endpoints; once one
# returns a usable id/token we lock the path for the rest of the warm
# container's lifetime. Saves a round-trip per Add Card after bootstrap.
_repay_tokenize_path: Optional[str] = None


def _get_repay_creds() -> Optional[Dict[str, str]]:
    """Fetch Repay credentials from Secrets Manager, cached per container.

    Expected shape (written by .github/workflows/store-repay-secrets.yml):
      gatewayApiUser, gatewaySecureToken, gatewayMerchantId,
      customerPortalUrl, customerPortalToken,
      achApiUser, achSecureToken, achMerchantId
    """
    global _repay_creds_cache
    if _repay_creds_cache:
        return _repay_creds_cache
    try:
        resp = _secrets.get_secret_value(SecretId=REPAY_SECRET_ARN)
        _repay_creds_cache = json.loads(resp["SecretString"])
        return _repay_creds_cache
    except Exception as e:
        log.warning("repay secret read failed arn=%s err=%s", REPAY_SECRET_ARN, e)
        return None


def _extract_repay_token(body: Any) -> Optional[str]:
    """Pull the card-vault identifier out of a Repay tokenize response.

    Different endpoints return the token under different keys; accept
    any of the likely ones and return the first non-empty string.
    """
    if not isinstance(body, dict):
        return None
    for key in ("id", "token", "card_id", "card_reference",
                "card_ref", "card_guid", "vault_id", "payment_method_id"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Sometimes wrapped: {data: {id: ...}} or {card: {id: ...}}
    for container in ("data", "card", "payment_method"):
        inner = body.get(container)
        if isinstance(inner, dict):
            tok = _extract_repay_token(inner)
            if tok:
                return tok
    return None


def _repay_tokenize_card(pan: str,
                         exp_month: int,
                         exp_year: int,
                         ccv: str,
                         zip_code: str,
                         cardholder_name: str) -> Optional[str]:
    """POST card details to Repay's RGAPI, return the tokenized card id.

    First call probes a short list of likely endpoints + body shapes;
    once one returns a usable token, the endpoint is cached. Full
    probe results are logged so we can lock to the winner.

    Returns the token string on success, or None (caller surfaces
    tokenization_failed to the UI).
    """
    global _repay_tokenize_path
    creds = _get_repay_creds()
    if not creds:
        return None

    api_user = creds.get("gatewayApiUser") or ""
    secure_token = creds.get("gatewaySecureToken") or ""
    merchant_id = creds.get("gatewayMerchantId") or ""
    if not (api_user and secure_token and merchant_id):
        log.warning("repay creds missing required fields; skipping tokenize")
        return None

    auth = base64.b64encode(f"{api_user}:{secure_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "X-Merchant-Id": str(merchant_id),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Two common body shapes; gateways differ on field names.
    body_snake = {
        "merchant_id": str(merchant_id),
        "card_number": pan,
        "expiration_month": exp_month,
        "expiration_year": exp_year,
        "cvv": ccv,
        "cardholder_name": cardholder_name,
        "billing_zip": zip_code,
    }
    body_camel = {
        "merchantId": str(merchant_id),
        "cardNumber": pan,
        "expirationMonth": exp_month,
        "expirationYear": exp_year,
        "cvv": ccv,
        "cardholderName": cardholder_name,
        "billingZip": zip_code,
    }

    # If we've locked an endpoint + body on a previous warm call, try it first.
    candidates = []
    if _repay_tokenize_path:
        candidates.append(_repay_tokenize_path)
    for p in ("/cards", "/tokens", "/payment_methods", "/vault/cards",
              "/card/tokenize", "/tokenize"):
        if p not in candidates:
            candidates.append(p)

    last4 = pan[-4:]
    tried = []
    for path in candidates:
        url = f"{REPAY_GATEWAY_BASE}{path}"
        for body_shape, shape_name in ((body_snake, "snake"), (body_camel, "camel")):
            status, parsed, raw = _http(url, "POST", body=body_shape, headers=headers)
            token = _extract_repay_token(parsed)
            tried.append(f"{path}:{shape_name}={status}")
            if status in (200, 201) and token:
                _repay_tokenize_path = path
                log.info("repay tokenize ok path=%s shape=%s last4=%s tried=%s",
                         path, shape_name, last4, tried)
                return token
            # 404 means wrong path — skip the camel retry for the same path.
            if status == 404:
                break
    # Exhausted candidates — log the full probe result so we can fix.
    flat_raw = (raw or "").replace("\n", " ")[:400] if raw else ""
    log.warning("repay tokenize failed last4=%s tried=%s last_raw=%s",
                last4, tried, flat_raw)
    return None


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

def _build_repay_body_card(*, cid, loan_id, card_id, amount, store_id,
                           user_id, idempotency_key):
    return {
        "CompanyId":     VERGENT_COMPANY_ID,
        "company_id":    VERGENT_COMPANY_ID,
        "CustomerId":    int(cid),
        "customer_id":   int(cid),
        "LoanId":        int(loan_id),
        "loan_id":       int(loan_id),
        "HeaderId":      int(loan_id),  # alias some Vergent endpoints use
        "header_id":     int(loan_id),
        "CardId":        int(card_id),
        "card_id":       int(card_id),
        "Amount":        round(float(amount), 2),
        "amount":        round(float(amount), 2),
        "PaymentAmount": round(float(amount), 2),
        "payment_amount": round(float(amount), 2),
        "StoreId":       int(store_id) if store_id else 0,
        "store_id":      int(store_id) if store_id else 0,
        "UserId":        int(user_id) if user_id else 0,
        "user_id":       int(user_id) if user_id else 0,
        "IdempotencyKey": idempotency_key or "",
        "idempotency_key": idempotency_key or "",
    }


def _build_repay_body_check(*, cid, loan_id, bank_id, amount, store_id,
                            user_id, idempotency_key):
    return {
        "CompanyId":     VERGENT_COMPANY_ID,
        "company_id":    VERGENT_COMPANY_ID,
        "CustomerId":    int(cid),
        "customer_id":   int(cid),
        "LoanId":        int(loan_id),
        "loan_id":       int(loan_id),
        "HeaderId":      int(loan_id),
        "header_id":     int(loan_id),
        "BankId":        int(bank_id),
        "bank_id":       int(bank_id),
        "Amount":        round(float(amount), 2),
        "amount":        round(float(amount), 2),
        "PaymentAmount": round(float(amount), 2),
        "payment_amount": round(float(amount), 2),
        "StoreId":       int(store_id) if store_id else 0,
        "store_id":      int(store_id) if store_id else 0,
        "UserId":        int(user_id) if user_id else 0,
        "user_id":       int(user_id) if user_id else 0,
        "IdempotencyKey": idempotency_key or "",
        "idempotency_key": idempotency_key or "",
    }


def _shape_repay_response(status, parsed, raw, *,
                          amount, last4, method, new_balance):
    """Translate Vergent /V1/repay/transaction/* response into the
    same {success, confirmationId, ...} shape `payments.js` expects.
    On non-2xx or business-logic decline, surfaces upstream body for
    diagnosis."""
    if status not in (200, 201):
        log.warning("repay/transaction/%s upstream status=%s raw=%s",
                    method, status, (raw or "")[:600])
        return _json_response(502, {
            "success": False,
            "error":   "upstream_unavailable",
            "upstreamStatus": status,
            "upstreamBody":   (raw or "")[:600],
        })
    # Some Vergent endpoints return a wrapped shape with Success: false
    # for declines. Surface as a clean failure if present.
    if isinstance(parsed, dict):
        success_flag = parsed.get("Success") or parsed.get("success")
        if success_flag is False:
            errs = (parsed.get("Errors") or parsed.get("errors")
                    or parsed.get("ErrorMessage") or parsed.get("Error"))
            log.warning("repay/transaction/%s declined parsed=%s",
                        method, str(parsed)[:400])
            return _json_response(200, {
                "success": False,
                "error":   "card_declined" if method == "card" else "ach_declined",
                "upstreamErrors": errs,
                "upstreamBody":   (raw or "")[:600],
            })
        confirmation_id = (parsed.get("TransactionId")
                           or parsed.get("transactionId")
                           or parsed.get("Id") or parsed.get("id")
                           or parsed.get("ConfirmationId")
                           or parsed.get("confirmationId"))
    else:
        confirmation_id = None
    if not confirmation_id:
        from datetime import datetime, timezone as _tz
        confirmation_id = datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
    return _json_response(200, {
        "success":        True,
        "confirmationId": str(confirmation_id),
        "transactionId":  confirmation_id,
        "amount":         round(float(amount), 2),
        "last4":          last4,
        "paymentMethod":  method,
        "newBalance":     new_balance,
        "via":            "repay-sync",
    })


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
    """POST /api/my-payment — charge a card OR debit a bank account.

    Body:
      { method: 'card' | 'bank',
        loanId, amount,
        cardId  (when method=card),
        bankId  (when method=bank),
        idempotencyKey }

    Both flows post directly to Vergent's Repay-gateway endpoints
    (POST /V1/repay/transaction/{card,check}/sync). Same v1 service
    token auth as everything else. Replaces the previous v2 → v1
    fallback chain that was broken at both layers.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    pay_method = (body.get("method") or "card").lower()
    loan_id = body.get("loanId")
    amount = body.get("amount")
    idempotency_key = (body.get("idempotencyKey") or "").strip()

    if loan_id is None or amount is None:
        return _json_response(400, {"error": "missing_fields"})
    try:
        amount_num = float(amount)
    except (TypeError, ValueError):
        return _json_response(400, {"error": "amount_invalid"})
    if amount_num <= 0:
        return _json_response(400, {"error": "amount_invalid"})

    # Ownership + payoff guard via v1 (unchanged from prior pipeline —
    # this part has always worked).
    loan = _fetch_active_loan(cid)
    if not loan or str(loan.get("id")) != str(loan_id):
        status_ok, raw_loans = _v1_get(f"/V1/{cid}/loans")
        found = None
        if status_ok == 200 and isinstance(raw_loans, list):
            for r in raw_loans:
                if isinstance(r, dict):
                    shaped = _shape_v1_loan(r)
                    if str(shaped.get("id")) == str(loan_id):
                        found = shaped
                        break
        if not found:
            log.warning("payment loan_not_yours cid=%s loan_id=%s", cid, loan_id)
            return _json_response(403, {"error": "loan_not_yours"})
        loan = found

    payoff = loan.get("payoffAmount") or loan.get("balance") or 0
    if amount_num > float(payoff) + 0.01:
        return _json_response(400, {"error": "amount_invalid", "payoff": payoff})

    store_id = loan.get("storeId") or 0

    # Prime the v1 service token so loans._v1_user_id is populated
    # (the Repay endpoints accept a UserId field for audit-attribution).
    _get_v1_token()
    from handlers import loans as _loans
    user_id = _loans._v1_user_id or 0

    if pay_method == "card":
        card_id = body.get("cardId")
        if card_id is None:
            return _json_response(400, {"error": "missing_fields"})
        # Ownership check against saved cards list.
        st_c, cards_body, _ = _v1_request("GET", f"/V1/GetCustomerCards?custId={cid}")
        if st_c != 200 or not isinstance(cards_body, list):
            return _json_response(502, {"error": "upstream_unavailable"})
        card = next(
            (c for c in cards_body if isinstance(c, dict)
             and str(c.get("id")) == str(card_id)),
            None,
        )
        if not card:
            return _json_response(403, {"error": "card_not_yours"})
        last4 = "".join(ch for ch in (card.get("card_number") or "")
                        if ch.isdigit())[-4:]

        log.info("payment-attempt method=card cid=%s loan_id=%s last4=%s amount=%s",
                 cid, loan_id, last4, amount_num)

        # Charge via v2 CustomerPortal CreditCardPayment using the
        # customer's Vergent portal token (obtained by exchanging the
        # request's Cognito JWT via /AuthenticateCognito). This is the
        # (Auth)-annotated path used by Vergent's own customer portal.
        # The v1 /V1/repay/transaction/card[/sync] endpoints are webhook
        # receivers Repay calls back to AFTER a payment is processed —
        # not charge-initiation endpoints — so there is no v1 fallback.
        trail: list = []
        customer_token = _get_customer_v2_token(event, trail=trail)
        if not customer_token:
            return _json_response(502, {
                "success": False,
                "error":   "v2_auth_failed",
                "_debug":  {"trail": trail},
            })

        v2_status, v2_parsed, v2_raw = (
            _v2_credit_card_payment_with_customer_token(
                customer_token=customer_token,
                loan_id=int(loan_id),
                payment_id=0,
                amount=amount_num,
                card_id=int(card_id),
                customer_id=int(cid) if cid else None,
            )
        )
        trail.append({
            "step":    "charge",
            "via":     "v2_customer_token",
            "status":  v2_status,
            "rawHead": (v2_raw or "")[:300],
        })
        log.info("v2 charge status=%s raw=%s",
                 v2_status, (v2_raw or "")[:400])

        if v2_status not in (200, 201):
            return _json_response(502, {
                "success":        False,
                "error":          "upstream_unavailable",
                "upstreamStatus": v2_status,
                "upstreamBody":   (v2_raw or "")[:600],
                "_debug":         {"trail": trail},
            })

        v2_success = True
        if isinstance(v2_parsed, dict):
            flag = (v2_parsed.get("success")
                    if v2_parsed.get("success") is not None
                    else v2_parsed.get("Success"))
            if flag is False:
                v2_success = False
        if not v2_success:
            errs = (v2_parsed.get("errors") or v2_parsed.get("Errors")
                    or v2_parsed.get("ErrorMessage")
                    or v2_parsed.get("Error")
                    if isinstance(v2_parsed, dict) else None)
            return _json_response(200, {
                "success":        False,
                "error":          "card_declined",
                "upstreamErrors": errs,
                "upstreamBody":   (v2_raw or "")[:600],
                "_debug":         {"trail": trail},
            })

        refreshed = _fetch_active_loan(cid)
        new_balance = refreshed.get("balance") if refreshed else None
        confirmation_id = None
        if isinstance(v2_parsed, dict):
            confirmation_id = (
                v2_parsed.get("transactionId")
                or v2_parsed.get("TransactionId")
                or v2_parsed.get("scheduleDate")
                or v2_parsed.get("ScheduleDate")
                or v2_parsed.get("confirmationId")
                or v2_parsed.get("ConfirmationId")
                or v2_parsed.get("id")
                or v2_parsed.get("Id")
            )
        if not confirmation_id:
            from datetime import datetime, timezone as _tz
            confirmation_id = (
                datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
            )
        return _json_response(200, {
            "success":        True,
            "confirmationId": str(confirmation_id),
            "transactionId":  confirmation_id,
            "amount":         round(float(amount_num), 2),
            "last4":          last4,
            "paymentMethod":  "card",
            "newBalance":     new_balance,
            "via":            "v2_customer_jwt",
        })

    elif pay_method == "bank":
        bank_id = body.get("bankId")
        if bank_id is None:
            return _json_response(400, {"error": "missing_fields"})
        st_b, banks_body, _ = _v1_request("GET", f"/V1/GetCustomerBanks?custId={cid}")
        if st_b != 200 or not isinstance(banks_body, list):
            return _json_response(502, {"error": "upstream_unavailable"})
        bank = next(
            (b for b in banks_body if isinstance(b, dict)
             and str(b.get("id")) == str(bank_id)),
            None,
        )
        if not bank:
            return _json_response(403, {"error": "bank_not_yours"})
        last4 = "".join(ch for ch in (bank.get("account_number") or "")
                        if ch.isdigit())[-4:]

        charge_body = _build_repay_body_check(
            cid=cid, loan_id=loan_id, bank_id=bank_id,
            amount=amount_num, store_id=store_id, user_id=user_id,
            idempotency_key=idempotency_key,
        )
        log.info("payment-attempt method=ach cid=%s loan_id=%s last4=%s amount=%s",
                 cid, loan_id, last4, amount_num)
        status, parsed, raw = _v1_request(
            "POST", "/V1/repay/transaction/check/sync", body=charge_body,
        )
        new_balance = None
        if status in (200, 201):
            refreshed = _fetch_active_loan(cid)
            new_balance = refreshed.get("balance") if refreshed else None
        return _shape_repay_response(
            status, parsed, raw,
            amount=amount_num, last4=last4, method="bank",
            new_balance=new_balance,
        )

    return _json_response(400, {"error": "method_invalid"})


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
