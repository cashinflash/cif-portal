"""
Customer Portal - Account + Loans handler (Vergent v1 LMS API).

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-profile                        -> profile card + addresses + phones
  PUT  /api/my-profile/email                  -> update Vergent email + notification
  PUT  /api/my-profile/address                -> update primary mailing address
  POST /api/my-profile/phone/start-verify     -> Vergent SMS PIN to new phone
  POST /api/my-profile/phone/confirm          -> verify SMS PIN + save phone
  GET  /api/my-loans/active                   -> active loan with balance / due date / status
  GET  /api/my-loans/activity                 -> recent activity for ?loanId=X
  GET  /api/my-loans/documents                -> list signed documents for ?loanId=X
  GET  /api/my-loans/documents/{docId}/download -> stream document binary (?format=pdf for PDF)
  POST /api/my-loan/new                       -> returns handoff URL into Vergent loan-application UI

Auth model:
  - API Gateway's Cognito JWT authorizer validates the ID token; claims
    land in event.requestContext.authorizer.jwt.claims.
  - We pull custom:vergentCustomerId from those claims (populated at
    signup by Round 19A's PreSignUp trigger).
  - Lambda authenticates as the SERVICE account once per container:
        POST https://shared.vergentlms.com/api/api/authenticate
        body:  {"LogonName": "...", "Password": "..."}  (PascalCase)
        resp:  {"Token": "<guid>", "Timeout": 86400, "User": {...}}
    Token cached ~1h per warm container.
  - Every customer-data call uses the `Token: <guid>` header against
    `https://shared.vergentlms.com/api/api/V1/...` (note the doubled
    /api/api — basePath is /api and paths already include /api/ prefix).

Security: the service credentials can read any customer at company 386.
We rely on the JWT authorizer to identify which customer this request
is about, then scope every Vergent call to that customer's id from the
JWT claim. Never trust customerId from request body/query.

Environment:
  VERGENT_V1_BASE_URL  default https://shared.vergentlms.com/api/api
                       (note the doubled /api/api — swagger basePath
                       is /api and paths begin with /api/)
  VERGENT_APIM_BASE_URL optional, for handoff (POST /api/authenticate/handoff/create
                        still lives on the APIM gateway)
  VERGENT_SECRET_ARN   Secrets Manager ARN, expects keys
                        logonName, password, xApiKey
  VERGENT_HANDOFF_AUTHORITY  default cashinflash.apply.vergentlms.com
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

# v1 LMS is at shared.vergentlms.com with doubled /api/api prefix
V1_BASE = os.environ.get(
    "VERGENT_V1_BASE_URL", "https://shared.vergentlms.com/api/api"
).rstrip("/")
# APIM is still the home for the handoff endpoint
APIM_BASE = os.environ.get(
    "VERGENT_APIM_BASE_URL", "https://prod.apim.vergentlms.com/external/shared"
).rstrip("/")
VERGENT_SECRET_ARN = os.environ["VERGENT_SECRET_ARN"]
HANDOFF_AUTHORITY = os.environ.get("VERGENT_HANDOFF_AUTHORITY", "cashinflash.apply.vergentlms.com")

_secrets = boto3.client("secretsmanager")
_lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_dynamo = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
DOC_PDF_FN_NAME = os.environ.get("DOC_PDF_FN_NAME", "")  # set by provision-doc-pdf.yml
PROFILE_REQUESTS_TABLE = os.environ.get(
    "PROFILE_REQUESTS_TABLE", "cif-portal-profile-change-requests-dev"
)
ADMIN_NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "info@cashinflash.com")
SES_SENDER_EMAIL = os.environ.get("SES_SENDER_EMAIL", "no-reply@cashinflash.com")
PORTAL_PUBLIC_URL = os.environ.get("PORTAL_PUBLIC_URL", "https://d1zucrj1ouu3c.cloudfront.net")
_creds_cache: Optional[Dict[str, str]] = None

# v1 service Token (GUID) — used on every v1 LMS call.
_v1_token: Optional[str] = None
_v1_token_exp: float = 0.0
_v1_user_id: Optional[int] = None  # returned alongside the Token; needed for history calls
VERGENT_COMPANY_ID = int(os.environ.get("VERGENT_COMPANY_ID", "386"))

# APIM service token (JWT) — used on handoff + v2 non-CustomerPortal endpoints.
_apim_token: Optional[str] = None
_apim_token_exp: float = 0.0

TOKEN_TTL_SECS = 60 * 60  # refresh once an hour even though Timeout is 24h

# Front-end origin allowed to call our API. Locked down from "*" so a
# malicious site can't relay a logged-in customer's browser into our
# API. Override via env var when adding a custom domain. Browsers will
# still block any cross-origin request that doesn't echo this back.
ALLOWED_ORIGIN = os.environ.get(
    "PORTAL_ORIGIN", "https://d1zucrj1ouu3c.cloudfront.net"
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Max-Age": "300",
    "Vary": "Origin",
    "Cache-Control": "no-store",
    # PCI / online-banking baseline security headers. HSTS forces HTTPS
    # for 2 years; nosniff kills MIME-sniff attacks; Referrer-Policy
    # prevents leaking auth-bearing URLs to third-party referrers;
    # Permissions-Policy disables sensors we never use.
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def _get_creds() -> Dict[str, str]:
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    resp = _secrets.get_secret_value(SecretId=VERGENT_SECRET_ARN)
    payload = json.loads(resp["SecretString"])
    _creds_cache = {
        "logonName": payload["logonName"],
        "password": payload["password"],
        "xApiKey": payload["xApiKey"],
    }
    return _creds_cache


def _json_response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _claims(event: Dict[str, Any]) -> Dict[str, Any]:
    rc = event.get("requestContext") or {}
    auth = rc.get("authorizer") or {}
    jwt = auth.get("jwt") or {}
    return jwt.get("claims") or {}


def _customer_id(claims: Dict[str, Any]) -> Optional[str]:
    cid = (
        claims.get("custom:vergentCustomerId")
        or claims.get("custom_vergentCustomerId")
        or claims.get("vergentCustomerId")
    )
    return str(cid) if cid else None


def _http(url: str, method: str = "GET", *, body: Optional[Dict[str, Any]] = None,
          headers: Optional[Dict[str, str]] = None, timeout: int = 12) -> Tuple[int, Optional[Any], str]:
    h = {"Accept": "application/json", "User-Agent": "cif-portal/1.0"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace") or ""
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw)
                    # Some Vergent endpoints double-encode as JSON strings.
                    if isinstance(parsed, str) and parsed.strip()[:1] in ("{", "["):
                        parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    parsed = None
            return resp.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        log.warning("Vergent %s %s -> %s: %s", method, url, e.code, raw[:300])
        return e.code, None, raw
    except (urllib.error.URLError, TimeoutError) as exc:
        log.error("Vergent %s %s network error: %s", method, url, exc)
        return 0, None, ""


# ─────────────────────────────────────────
# Service token caches
# ─────────────────────────────────────────
def _get_v1_token() -> Optional[str]:
    """v1 LMS service token (GUID) — used on every v1 customer call."""
    global _v1_token, _v1_token_exp, _v1_user_id
    if _v1_token and _v1_token_exp > time.time():
        return _v1_token
    creds = _get_creds()
    status, body, _raw = _http(
        f"{V1_BASE}/authenticate",
        "POST",
        body={"LogonName": creds["logonName"], "Password": creds["password"]},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("v1 authenticate failed status=%s", status)
        return None
    token = body.get("Token") or body.get("token")
    if not token:
        log.warning("v1 authenticate returned no Token")
        return None
    _v1_token = token
    _v1_token_exp = time.time() + TOKEN_TTL_SECS
    user = body.get("User") or body.get("user") or {}
    if isinstance(user, dict):
        uid = user.get("UserId") or user.get("userId") or user.get("Id")
        try:
            _v1_user_id = int(uid) if uid is not None else _v1_user_id
        except (TypeError, ValueError):
            pass
    log.info("v1 service Token cached (%ds) userId=%s", TOKEN_TTL_SECS, _v1_user_id)
    return token


def _get_apim_token() -> Optional[str]:
    """APIM service token (JWT) — used for handoff and other v2 paths."""
    global _apim_token, _apim_token_exp
    if _apim_token and _apim_token_exp > time.time():
        return _apim_token
    creds = _get_creds()
    status, body, _raw = _http(
        f"{APIM_BASE}/api/authenticate",
        "POST",
        body={"userName": creds["logonName"], "password": creds["password"]},
        headers={"x-api-key": creds["xApiKey"]},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("APIM authenticate failed status=%s", status)
        return None
    token = body.get("auth_token") or body.get("token") or body.get("Token")
    if not token:
        return None
    _apim_token = token
    _apim_token_exp = time.time() + TOKEN_TTL_SECS
    return token


def _v1_get(path: str) -> Tuple[int, Optional[Any]]:
    token = _get_v1_token()
    if not token:
        return 0, None
    status, body, _raw = _http(f"{V1_BASE}{path}", "GET", headers={"Token": token})
    if status in (401, 403):
        # Force refresh once.
        global _v1_token_exp
        _v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, body, _raw = _http(f"{V1_BASE}{path}", "GET", headers={"Token": tok2})
    return status, body


def _v1_request(method: str, path: str,
                body: Optional[Dict[str, Any]] = None,
                return_raw: bool = False):
    """Generic v1 call with method override. Used by profile-edit
    endpoints (PUT/POST) — _v1_get only handles GETs. Same token
    refresh-on-401 behaviour.

    Returns (status, parsed) by default. With return_raw=True, returns
    (status, parsed, raw_body) so callers can surface diagnostic info
    when an endpoint returns an unexpected status.
    """
    token = _get_v1_token()
    if not token:
        return (0, None, "") if return_raw else (0, None)
    status, resp, raw = _http(
        f"{V1_BASE}{path}", method,
        body=body, headers={"Token": token},
    )
    if status in (401, 403):
        global _v1_token_exp
        _v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, resp, raw = _http(
                f"{V1_BASE}{path}", method,
                body=body, headers={"Token": tok2},
            )
    if return_raw:
        return status, resp, raw
    return status, resp


def _communication_pin_request(path: str,
                                body: Dict[str, Any]) -> Tuple[int, Optional[Any], str, str]:
    """POST to a /Communication/* endpoint (e.g. RequestPinByText,
    VerifyPin). Tries the v1 host first with the service Token, then
    falls back to the APIM host with Bearer + x-api-key on 401/403.

    Returns (status, parsed, raw, used_host) where used_host is
    'v1' or 'apim' or 'none' (if no auth available).
    """
    creds = _get_creds()
    api_key = creds.get("xApiKey") if isinstance(creds, dict) else None

    v1_tok = _get_v1_token()
    if v1_tok:
        url = f"{V1_BASE}{path}"
        headers = {"Token": v1_tok}
        if api_key:
            headers["x-api-key"] = api_key
        status, parsed, raw = _http(url, "POST", body=body, headers=headers)
        if status not in (401, 403):
            return status, parsed, raw, "v1"

    apim_tok = _get_apim_token()
    if apim_tok:
        url = f"{APIM_BASE}{path}"
        headers = {"Authorization": f"Bearer {apim_tok}"}
        if api_key:
            headers["x-api-key"] = api_key
        status, parsed, raw = _http(url, "POST", body=body, headers=headers)
        return status, parsed, raw, "apim"

    return 0, None, "", "none"


# ─────────────────────────────────────────
# Shape helpers
# ─────────────────────────────────────────
def _pick(d: Optional[Dict[str, Any]], *keys: str) -> Any:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _to_number(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mask_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = [c for c in raw if c.isdigit()]
    if len(digits) >= 4:
        return f"•••-•••-{''.join(digits[-4:])}"
    return raw


def _format_iso(dt: Optional[str]) -> Optional[str]:
    if not dt:
        return None
    # Vergent returns "2026-04-19T00:00:00" — pass through; frontend will format.
    return dt


def _shape_v1_loan(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one v1 loan record → the shape the dashboard renders."""
    hdr = record.get("LoanHeader") if isinstance(record.get("LoanHeader"), dict) else record
    detail = record.get("LoanDetail") if isinstance(record.get("LoanDetail"), dict) else {}
    is_outstanding = bool(hdr.get("IsStatusOutstanding"))
    status_id = hdr.get("StatusId")
    loan_amount = _to_number(hdr.get("LoanAmount"))
    payoff = _to_number(hdr.get("PayoffAmount"))
    amount_due = _to_number(hdr.get("AmountDue"))
    min_due = _to_number(hdr.get("MinAmountDue"))

    # "Amount due" on the UI should be what the customer actually owes on
    # the due date — principal + fees. For a payday loan that's AmountDue
    # (total) or PayoffAmount. MinAmountDue can be just the fee portion
    # in Vergent's model and is NOT what we want to display.
    next_due = amount_due if amount_due is not None else (payoff if payoff is not None else min_due)

    # Fee amount — try several field names Vergent may use, then fall
    # back to (balance - principal) which is exact for an untouched
    # payday loan. Becomes inaccurate once partial payments shrink the
    # balance; we'll lock this to a specific field once the full key
    # probe below shows us the real one.
    fees = None
    for fk in ("OriginalFees", "Fees", "LoanFees", "FeeAmount",
               "OriginalFeeAmount", "FinanceCharge", "TotalFees"):
        v = hdr.get(fk)
        if v is not None:
            fees = _to_number(v)
            if fees is not None:
                break
    if fees is None and isinstance(detail, dict):
        for fk in ("OriginalFees", "Fees", "FeeAmount", "FinanceCharge"):
            v = detail.get(fk)
            if v is not None:
                fees = _to_number(v)
                if fees is not None:
                    break
    if fees is None:
        if payoff is not None and loan_amount is not None and payoff > loan_amount:
            fees = round(payoff - loan_amount, 2)
        elif amount_due is not None and loan_amount is not None and amount_due > loan_amount:
            fees = round(amount_due - loan_amount, 2)

    # Autopay pill — disabled until we verify which Vergent v1 field
    # actually means "a payment is scheduled right now" for our tenant.
    # The IsACHOrCardPaymentScheduled flag and the various date fields
    # we've tried all fire false-positives for loans without a pending
    # debit (confirmed with Harut's loan 2026-04-21).
    # TODO: once CloudWatch shows which key lights up when Vergent
    # staff actually schedules a card/ACH payment, re-enable here.
    scheduled_date = (
        hdr.get("NextACHPaymentDate")
        or hdr.get("ScheduledPaymentDate")
        or hdr.get("NextScheduledPaymentDate")
        or hdr.get("AchPaymentDate")
        or hdr.get("NextPaymentScheduledDate")
    )
    autopay = False  # conservative default; see TODO above

    return {
        "id": hdr.get("hdr_id"),
        "publicId": detail.get("PublicLoanId") or hdr.get("PublicLoanId"),
        "loanClass": hdr.get("LoanModelName") or hdr.get("LoanTypeName", "").split(".")[-1] or None,
        "status": (
            "Current" if is_outstanding
            else (hdr.get("SubStatus")
                  or ("Paid Off" if status_id in (3,) else "Closed"))
        ),
        "statusId": status_id,
        "subStatus": hdr.get("SubStatus"),
        "rawStatus": hdr.get("Status"),
        "isOutstanding": is_outstanding,
        "principal": loan_amount,
        "balance": payoff if payoff is not None else amount_due,
        "payoffAmount": payoff,
        "amountDue": amount_due,
        "minAmountDue": min_due,
        "nextDueDate": _format_iso(hdr.get("DueDate") or hdr.get("NextPaymentDate")),
        "nextDueAmount": next_due,
        "originationDate": _format_iso(hdr.get("OriginationDate")),
        "loanDate": _format_iso(hdr.get("LoanDate")),
        "storeId": hdr.get("StoreId"),
        "storeName": detail.get("StoreName") or hdr.get("StoreName"),
        "daysLate": detail.get("DaysLate"),
        "isEligibleForRefi": bool(hdr.get("IsEligibleForRefi") or False),
        "isInRescindPeriod": bool(hdr.get("IsInRescindPeriod") or False),
        "apr": _to_number(hdr.get("OriginalFeeApr")),
        "fees": fees,
        "feeBalance": _to_number(hdr.get("FeeBalance")),
        "numberOfPayments": hdr.get("NumberOfPayments"),
        "autopay": autopay,
        "scheduledPaymentDate": _format_iso(scheduled_date),
    }


# Vergent v1 statusId values we treat as "real, paid-off" loan history
# that the customer should see. Discovered empirically via the DevTools
# probe on Harut's account 2026-05-01:
#   statusId 3  -> Paid Off    (the 1 loan he actually paid off)
#   statusId 10 -> Deleted     (the 2 ghost application records)
# Vergent's text status fields (Status, SubStatus) are NULL for these
# records so the only reliable distinguishing field is statusId.
# Add additional paid-off variants here as we encounter them (e.g. if
# Vergent uses a separate code for "Paid In Full" or "Settled").
_PAID_OFF_STATUS_IDS = {3}


def _is_visible_loan(loan: Dict[str, Any]) -> bool:
    """Filter Vergent's raw loan list down to what a customer should see.

    Customers should see:
      - outstanding (current) loans
      - paid-off loans (Vergent statusId in _PAID_OFF_STATUS_IDS)
      - any loan with explicit "paid" text in a status field
        (forward-compat fallback for records where Vergent fills
        in Status/SubStatus instead of leaving them null)
    Everything else (Deleted, Cancelled, ghost application records,
    etc.) is hidden everywhere — history page, dashboard list,
    activity, documents.
    """
    if loan.get("isOutstanding"):
        return True

    sid = loan.get("statusId")
    try:
        if int(sid) in _PAID_OFF_STATUS_IDS:
            return True
    except (TypeError, ValueError):
        pass

    # Forward-compat: if any status text field explicitly says "paid",
    # show the loan even if its statusId isn't in our known set.
    candidates = (loan.get("status"), loan.get("subStatus"), loan.get("rawStatus"))
    for raw in candidates:
        if raw and "paid" in str(raw).strip().lower():
            return True

    return False


def _fetch_all_loans(cid: str) -> List[Dict[str, Any]]:
    """Fetch every visible loan for a customer (outstanding + paid-off).

    v1's plain `/V1/{cid}/loans` returns open loans only by default. We
    try the broadest endpoint first and fall back, logging which path
    Vergent actually serves so we can simplify later if a tier proves
    redundant. Returns an empty list if every attempt fails. Hides
    loans that were never real (Deleted, Cancelled, etc.) via
    `_is_visible_loan`.
    """
    candidates = (
        f"/V1/{cid}/loans/all",
        f"/V1/{cid}/loans?includePrevious=true&numresults=200",
        f"/V1/{cid}/loans",
    )
    for path in candidates:
        status, body = _v1_get(path)
        if status == 200 and isinstance(body, list):
            shaped = [_shape_v1_loan(item) for item in body if isinstance(item, dict)]
            return [l for l in shaped if _is_visible_loan(l)]
    return []


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_my_profile(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)

    # Base from Cognito claims — always available
    profile = {
        "firstName": claims.get("given_name"),
        "lastName": claims.get("family_name"),
        "email": (claims.get("email") or "").strip(),
        "emailVerified": claims.get("email_verified") in (True, "true"),
        "phone": claims.get("phone_number"),
        "phoneVerified": claims.get("phone_number_verified") in (True, "true"),
        "vergentCustomerId": cid,
        "statusName": None,
        "storeName": None,
        "vergentPhoneHint": None,
        "vergentEmail": None,
        "isSecurityQuestionsSetup": None,
        "source": "cognito",
    }

    if not cid:
        return _json_response(200, profile)

    # v1 customer profile — gives us status + store + SSN status + SecurityQuestion flag
    status, body = _v1_get(f"/V1/GetCustomer/{cid}")
    if status == 200 and isinstance(body, dict):
        profile["statusName"] = body.get("Status")
        profile["storeName"] = body.get("StoreName")
        profile["vergentEmail"] = body.get("EmailAddr")
        profile["isSecurityQuestionsSetup"] = bool(body.get("SecurityQuestionId"))
        profile["source"] = "vergent"

    # v1 customer data — includes addresses + phones. We surface both
    # in full (not just a hint) because the profile-edit page reads
    # them. Numbers are full E.164/raw values; the dashboard masks
    # for its summary card via vergentPhoneHint, the profile page
    # uses the full versions for editing context.
    status2, data = _v1_get(f"/V1/GetCustomerData/{cid}")
    if status2 == 200 and isinstance(data, dict):
        phones = data.get("custPhones") or []
        addresses = data.get("custAddresses") or []
        if isinstance(phones, list):
            # v1 returns snake_case keys: is_primary, number, type_name, type_id.
            primary_phone = next(
                (p for p in phones if isinstance(p, dict) and p.get("is_primary")),
                next((p for p in phones if isinstance(p, dict)), None),
            )
            if primary_phone:
                profile["vergentPhoneHint"] = _mask_phone(primary_phone.get("number"))
                profile["vergentPhone"] = primary_phone.get("number")
                profile["vergentPhoneTypeId"] = primary_phone.get("type_id")
            profile["vergentPhones"] = [
                {
                    "id": p.get("id"),
                    "number": p.get("number"),
                    "typeId": p.get("type_id"),
                    "typeName": p.get("type_name"),
                    "isPrimary": bool(p.get("is_primary")),
                }
                for p in phones if isinstance(p, dict)
            ]
        if isinstance(addresses, list):
            primary_addr = next(
                (a for a in addresses if isinstance(a, dict) and a.get("IsPrimary")),
                next((a for a in addresses if isinstance(a, dict)), None),
            )
            if primary_addr:
                profile["vergentAddress"] = {
                    "id": primary_addr.get("id"),
                    "addr1": primary_addr.get("addr1"),
                    "addr2": primary_addr.get("addr2"),
                    "city": primary_addr.get("city"),
                    "state": primary_addr.get("abbrev") or primary_addr.get("state"),
                    "stateId": primary_addr.get("state_id"),
                    "zip": primary_addr.get("zip"),
                    "typeId": primary_addr.get("type_id"),
                }

    return _json_response(200, profile)


# ─────────────────────────────────────────
# Profile editing helpers
# ─────────────────────────────────────────
def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _normalize_us_phone(raw: str) -> Optional[str]:
    """Returns 10-digit US phone or None. Strips formatting,
    removes leading '1' country code if present."""
    d = _digits_only(raw)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) == 10:
        return d
    return None


def _validate_email(s: str) -> bool:
    if not s or len(s) > 254 or "@" not in s:
        return False
    local, _, domain = s.rpartition("@")
    return bool(local) and bool(domain) and "." in domain and " " not in s


def _create_change_request(cid: str, claims: Dict[str, Any],
                           field: str,
                           current_value: Any,
                           requested_value: Any,
                           extra_meta: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Queue a customer's profile-change request for admin review.

    Writes a record to the profile-change-requests DDB table and emails
    the admin notification address with the details. Returns (ok, reason)
    where reason is empty on success or a short error code on failure.

    No call to Vergent here — that happens out-of-band when an admin
    reviews the request and applies it via Vergent admin UI (or a
    future admin portal).

    `extra_meta` carries field-specific bits (e.g. phone-verified flag)
    that the email rendering uses to give the admin context.
    """
    import time
    import uuid

    request_id = str(uuid.uuid4())
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    ttl = int(time.time()) + 90 * 24 * 60 * 60  # 90-day audit-trail retention

    extra = extra_meta or {}

    def _ddb_value(v):
        if v is None:
            return {"NULL": True}
        if isinstance(v, bool):
            return {"BOOL": v}
        if isinstance(v, (int, float)):
            return {"N": str(v)}
        if isinstance(v, dict):
            return {"S": json.dumps(v, default=str)}
        return {"S": str(v)}

    item = {
        "requestId":      {"S": request_id},
        "customerId":     {"S": str(cid)},
        "field":          {"S": field},
        "currentValue":   _ddb_value(current_value),
        "requestedValue": _ddb_value(requested_value),
        "status":         {"S": "pending"},
        "requestedAt":    {"S": now_iso},
        "requestedByEmail": {"S": (claims.get("email") or "").strip()},
        "expiresAt":      {"N": str(ttl)},
    }
    if extra:
        item["meta"] = {"S": json.dumps(extra, default=str)}

    try:
        _dynamo.put_item(TableName=PROFILE_REQUESTS_TABLE, Item=item)
    except ClientError as e:
        log.error("DDB put_item failed for change request: %s",
                  e.response.get("Error", {}).get("Code"))
        return False, "queue_unavailable"
    except Exception as e:
        log.error("DDB put_item unexpected: %s", type(e).__name__)
        return False, "queue_unavailable"

    # Send admin email best-effort. Even if email fails, the request
    # IS in DDB so an admin reviewing the queue still sees it.
    _send_admin_notification(request_id, cid, claims, field,
                              current_value, requested_value, extra)

    # Customer-facing confirmation email — closes the loop so they
    # know their request landed. Best-effort; the queue is the
    # source of truth.
    _send_customer_confirmation(claims, field, requested_value, extra)
    return True, ""


def _send_admin_notification(request_id: str, cid: str, claims: Dict[str, Any],
                              field: str, current: Any, requested: Any,
                              extra: Dict[str, Any]) -> None:
    """Send a plaintext+HTML notification to ADMIN_NOTIFY_EMAIL with
    the change-request details. Best effort — failures are logged but
    do not propagate to the customer."""
    customer_name = (
        ((claims.get("given_name") or "") + " " + (claims.get("family_name") or "")).strip()
        or claims.get("email")
        or "Unknown customer"
    )
    customer_email = (claims.get("email") or "").strip()

    field_labels = {
        "email":   "Email address",
        "phone":   "Mobile phone (SMS-verified)",
        "address": "Mailing address",
    }
    field_label = field_labels.get(field, field)

    def _fmt(v):
        if v is None or v == "":
            return "(not set)"
        if isinstance(v, dict):
            return ", ".join(f"{k}: {vv}" for k, vv in v.items() if vv)
        return str(v)

    cur_str = _fmt(current)
    new_str = _fmt(requested)

    extra_lines = []
    if field == "phone" and extra.get("phoneVerified"):
        extra_lines.append("✓ Customer entered the SMS verification code we sent to the new phone.")

    body_text = (
        f"Profile change request — pending admin review\n\n"
        f"Customer:\n"
        f"  Name:           {customer_name}\n"
        f"  Customer ID:    {cid}\n"
        f"  Sign-in email:  {customer_email}\n\n"
        f"Change requested:\n"
        f"  Field:          {field_label}\n"
        f"  Current value:  {cur_str}\n"
        f"  Requested:      {new_str}\n"
        + ("".join(f"  {line}\n" for line in extra_lines))
        + f"\nRequest ID:       {request_id}\n"
        f"Submitted at:     {datetime.utcnow().isoformat(timespec='seconds')} UTC\n\n"
        f"To approve, log into Vergent admin and apply the change there.\n"
        f"To deny, contact the customer at {customer_email}.\n\n"
        f"---\n"
        f"This is an automated notification from the Cash in Flash customer portal.\n"
    )

    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;">
        <tr><td style="background:#0E8741;padding:20px 24px;color:#fff;">
          <h2 style="margin:0;font-size:18px;font-weight:700;">Profile change request — pending review</h2>
        </td></tr>
        <tr><td style="padding:24px 28px;font-size:14px;line-height:1.55;">
          <p style="margin:0 0 16px;"><strong>Customer:</strong> {customer_name} (ID {cid}) &middot; <a href="mailto:{customer_email}" style="color:#0E8741;">{customer_email}</a></p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;margin-bottom:16px;">
            <tr><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;width:140px;">Field</td><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;font-weight:600;">{field_label}</td></tr>
            <tr><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;">Current</td><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;">{cur_str}</td></tr>
            <tr><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;">Requested</td><td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#0E8741;font-weight:600;">{new_str}</td></tr>
            {('<tr><td style="padding:8px 0;color:#6b7280;">Verified</td><td style="padding:8px 0;color:#0E8741;">' + extra_lines[0] + '</td></tr>') if extra_lines else ''}
          </table>
          <p style="margin:0 0 8px;font-size:13px;color:#6b7280;">Request ID: <code style="font-size:12px;">{request_id}</code></p>
          <p style="margin:0;font-size:13px;color:#6b7280;">Submitted at {datetime.utcnow().isoformat(timespec='seconds')} UTC.</p>
          <p style="margin:20px 0 0;font-size:13px;color:#1a1a2e;"><strong>To approve:</strong> log into Vergent admin and apply the change manually.<br><strong>To deny:</strong> contact the customer.</p>
        </td></tr>
        <tr><td style="padding:16px 28px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:11px;">
          Cash in Flash — internal admin notification
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    subject = f"Profile change request: {field_label} — {customer_name}"

    try:
        _ses.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={"ToAddresses": [ADMIN_NOTIFY_EMAIL]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
    except ClientError as e:
        log.error("SES admin notification failed: %s",
                  e.response.get("Error", {}).get("Code"))
    except Exception as e:
        log.error("SES admin notification unexpected: %s", type(e).__name__)


def _send_customer_confirmation(claims: Dict[str, Any], field: str,
                                  requested: Any, extra: Dict[str, Any]) -> None:
    """Send a banking-style 'we received your request' email to the
    customer's sign-in inbox. Best-effort — failures log but don't
    propagate. The queue is the source of truth either way."""
    customer_email = (claims.get("email") or "").strip()
    if not customer_email:
        return

    first_name = (claims.get("given_name") or "").strip() or "there"

    field_labels = {
        "email":   "email address",
        "phone":   "mobile phone number",
        "address": "mailing address",
    }
    field_label = field_labels.get(field, field)

    def _fmt_request(v):
        if v is None or v == "":
            return ""
        if isinstance(v, dict):
            parts = [v.get("addr1"), v.get("addr2"), v.get("city"),
                     v.get("state"), v.get("zip")]
            return ", ".join(p for p in parts if p)
        return str(v)

    requested_display = _fmt_request(requested)

    subject = "Cash in Flash — we received your request"

    body_text = (
        f"Hi {first_name},\n\n"
        f"We've received your request to update the {field_label} on "
        f"your Cash in Flash account.\n\n"
        + (f"Requested: {requested_display}\n\n" if requested_display else "")
        + "Our team will review and confirm the change with you within "
          "one business day. For your security, this update won't take "
          "effect until we've verified it.\n\n"
          "If you didn't request this, please call us right away at "
          "(747) 270-7121.\n\n"
          "Thank you for being a Cash in Flash customer.\n\n"
          "— The Cash in Flash Team\n\n"
          "---\n"
          "Cash in Flash · Licensed by the California Department of "
          "Financial Protection and Innovation #214840\n"
          "This is an automated message. Please do not reply to this email.\n"
    )

    requested_row = (
        f'<tr><td style="padding:10px 0;color:#6b7280;width:140px;">Requested</td>'
        f'<td style="padding:10px 0;color:#1a1a2e;font-weight:600;">{requested_display}</td></tr>'
    ) if requested_display else ""

    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:32px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="background:#0E8741;padding:24px 28px;">
          <h1 style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.01em;">We received your request</h1>
        </td></tr>
        <tr><td style="padding:28px;font-size:15px;line-height:1.6;color:#1a1a2e;">
          <p style="margin:0 0 16px;">Hi {first_name},</p>
          <p style="margin:0 0 16px;">We've received your request to update the <strong>{field_label}</strong> on your Cash in Flash account.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;margin:16px 0 20px;background:#f9fafb;border-radius:8px;">
            <tr><td style="padding:0 16px;">
              <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;">
                {requested_row}
              </table>
            </td></tr>
          </table>
          <p style="margin:0 0 16px;">Our team will review and confirm the change with you within <strong>one business day</strong>. For your security, this update won't take effect until we've verified it.</p>
          <p style="margin:0 0 16px;color:#6b7280;font-size:13px;">If you didn't request this change, please call us right away at <a href="tel:+17472707121" style="color:#0E8741;font-weight:600;text-decoration:none;">(747) 270-7121</a>.</p>
          <p style="margin:24px 0 0;">Thank you for being a Cash in Flash customer.</p>
          <p style="margin:8px 0 0;color:#6b7280;">— The Cash in Flash Team</p>
        </td></tr>
        <tr><td style="padding:20px 28px;border-top:1px solid #e5e7eb;background:#fafafa;color:#6b7280;font-size:11px;line-height:1.5;">
          Cash in Flash &middot; Licensed by the California Department of Financial Protection and Innovation #214840<br>
          This is an automated message. Please do not reply to this email.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    try:
        _ses.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={"ToAddresses": [customer_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
    except ClientError as e:
        log.error("SES customer confirmation failed: %s",
                  e.response.get("Error", {}).get("Code"))
    except Exception as e:
        log.error("SES customer confirmation unexpected: %s", type(e).__name__)


def update_email(event: Dict[str, Any]) -> Dict[str, Any]:
    """PUT /api/my-profile/email — queue an email-change REQUEST for
    admin review. We don't push to Vergent directly; an admin reviews
    the queued request and applies it via Vergent admin UI.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    new_email = (body.get("email") or "").strip().lower()
    if not _validate_email(new_email):
        return _json_response(400, {"error": "invalid_email"})

    # Look up current Vergent email so the admin sees old vs new.
    current_email = ""
    status, prof = _v1_get(f"/V1/GetCustomer/{cid}")
    if status == 200 and isinstance(prof, dict):
        current_email = (prof.get("EmailAddr") or "").strip()

    if current_email and current_email.lower() == new_email:
        return _json_response(400, {"error": "no_change"})

    ok, reason = _create_change_request(
        cid, claims, "email",
        current_value=current_email or None,
        requested_value=new_email,
    )
    if not ok:
        return _json_response(502, {"error": reason})

    return _json_response(200, {"ok": True, "status": "pending_review"})


def update_address(event: Dict[str, Any]) -> Dict[str, Any]:
    """PUT /api/my-profile/address — queue an address-change REQUEST
    for admin review. Validation only; no Vergent write."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    addr1 = (body.get("addr1") or "").strip()
    addr2 = (body.get("addr2") or "").strip()
    city = (body.get("city") or "").strip()
    state = (body.get("state") or "").strip().upper()
    zip_code = _digits_only(body.get("zip") or "")[:9]

    if not addr1 or len(addr1) > 120:
        return _json_response(400, {"error": "addr1_invalid"})
    if not city or len(city) > 80:
        return _json_response(400, {"error": "city_invalid"})
    if len(state) != 2:
        return _json_response(400, {"error": "state_invalid"})
    if len(zip_code) not in (5, 9):
        return _json_response(400, {"error": "zip_invalid"})

    # Look up current address so the admin sees old vs new.
    current = None
    status, data = _v1_get(f"/V1/GetCustomerData/{cid}")
    if status == 200 and isinstance(data, dict):
        addrs = data.get("custAddresses") or []
        if isinstance(addrs, list):
            primary = next(
                (a for a in addrs if isinstance(a, dict) and a.get("IsPrimary")),
                next((a for a in addrs if isinstance(a, dict)), None),
            )
            if primary:
                current = {
                    "addr1": primary.get("addr1"),
                    "addr2": primary.get("addr2"),
                    "city": primary.get("city"),
                    "state": primary.get("abbrev") or primary.get("state"),
                    "zip": primary.get("zip"),
                }

    requested = {
        "addr1": addr1, "addr2": addr2 or None,
        "city": city, "state": state, "zip": zip_code,
    }

    ok, reason = _create_change_request(
        cid, claims, "address",
        current_value=current,
        requested_value=requested,
    )
    if not ok:
        return _json_response(502, {"error": reason})

    return _json_response(200, {"ok": True, "status": "pending_review"})


def start_phone_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-profile/phone/start-verify — kick off Vergent's
    SMS PIN flow against the new phone. Customer enters the code in
    the next step (confirm_phone_verify) before we save the change.

    This is the security boundary that keeps a stolen session from
    pivoting to MFA-takeover: changing the phone requires control of
    the new phone first.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    phone = _normalize_us_phone(body.get("phone") or "")
    if not phone:
        return _json_response(400, {"error": "invalid_phone"})

    # Use Vergent's standalone Communication controller — takes the
    # phone in the body and doesn't require it to already be on the
    # customer's record (unlike the V1 customer-communication path,
    # which is for re-verifying an existing phone). Tries v1 host
    # first, falls back to APIM on 401/403.
    last4 = phone[-4:] if len(phone) >= 4 else phone
    trigger_type = int(os.environ.get("VERGENT_PHONE_VERIFY_TYPE", "1"))
    group_type = int(os.environ.get("VERGENT_PHONE_VERIFY_GROUP", "0"))
    status, parsed, raw, host = _communication_pin_request(
        "/Communication/RequestPinByText",
        {"phoneNumber": phone, "type": trigger_type, "groupType": group_type},
    )
    log.info("phone request-pin type=%s group=%s status=%s host=%s cid=%s last4=%s body=%s",
             trigger_type, group_type, status, host, cid, last4, (raw or "")[:400])

    # Vergent returns PhoneVerificationResponseModel: {result, errorCode, message}
    # Treat HTTP 200 + result==false as a soft failure with diagnostic.
    result_ok = isinstance(parsed, dict) and bool(parsed.get("result"))

    if status != 200 or not result_ok:
        log.warning("phone request-pin failed status=%s host=%s cid=%s last4=%s",
                    status, host, cid, last4)
        return _json_response(502, {
            "error": "sms_send_failed",
            "upstreamStatus": status,
            "upstreamBody": (raw or "")[:400],
            "triedHost": host,
            "type": trigger_type,
            "groupType": group_type,
        })

    return _json_response(200, {"ok": True, "maskedPhone": _mask_phone(phone)})


def confirm_phone_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-profile/phone/confirm — verify the SMS PIN, then
    QUEUE the phone change for admin review (we don't push to Vergent
    directly). The PIN check guarantees the customer controls the new
    number before it ever lands in the admin queue."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    phone = _normalize_us_phone(body.get("phone") or "")
    code = _digits_only(body.get("code") or "")
    if not phone:
        return _json_response(400, {"error": "invalid_phone"})
    if len(code) < 4 or len(code) > 8:
        return _json_response(400, {"error": "invalid_code"})

    # Verify the PIN via Vergent's Communication controller. Same
    # type/groupType values as start-verify; phone + pin in body.
    last4 = phone[-4:] if len(phone) >= 4 else phone
    trigger_type = int(os.environ.get("VERGENT_PHONE_VERIFY_TYPE", "1"))
    group_type = int(os.environ.get("VERGENT_PHONE_VERIFY_GROUP", "0"))
    status, parsed, raw, host = _communication_pin_request(
        "/Communication/VerifyPin",
        {"phoneNumber": phone, "pin": code,
         "type": trigger_type, "groupType": group_type},
    )
    log.info("phone verify-pin type=%s group=%s status=%s host=%s cid=%s last4=%s body=%s",
             trigger_type, group_type, status, host, cid, last4, (raw or "")[:400])

    result_ok = isinstance(parsed, dict) and bool(parsed.get("result"))

    if status != 200 or not result_ok:
        log.warning("phone verify-pin failed status=%s host=%s cid=%s last4=%s",
                    status, host, cid, last4)
        return _json_response(400, {
            "error": "code_invalid_or_expired",
            "upstreamStatus": status,
            "upstreamBody": (raw or "")[:400],
            "triedHost": host,
        })

    # Look up current phone so admin sees old vs new.
    current_phone = None
    st2, data = _v1_get(f"/V1/GetCustomerData/{cid}")
    if st2 == 200 and isinstance(data, dict):
        phones = data.get("custPhones") or []
        if isinstance(phones, list):
            primary = next(
                (p for p in phones if isinstance(p, dict) and p.get("is_primary")),
                next((p for p in phones if isinstance(p, dict)), None),
            )
            if primary:
                current_phone = primary.get("number")

    ok, reason = _create_change_request(
        cid, claims, "phone",
        current_value=current_phone,
        requested_value=phone,
        extra_meta={"phoneVerified": True},
    )
    if not ok:
        return _json_response(502, {"error": reason})

    return _json_response(200, {"ok": True, "status": "pending_review",
                                 "maskedPhone": _mask_phone(phone)})


def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None, "reason": "no-customer-id"})

    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(200, {"loan": None, "loanCount": 0, "allLoans": []})

    # The "active loan" card on the dashboard should show only a current
    # (outstanding) loan. If the customer has none — even if they have
    # paid-off loans in their history — return loan=null so the dashboard
    # renders its empty state. The full history (paid-off + outstanding)
    # is still surfaced via allLoans for the My Loans list and page.
    outstanding = [l for l in shaped if l.get("isOutstanding")]
    active = outstanding[0] if outstanding else None
    return _json_response(200, {"loan": active, "loanCount": len(shaped), "allLoans": shaped})


def _parse_limit(event: Dict[str, Any], default: int = 5, cap: int = 50) -> int:
    qs = event.get("queryStringParameters") or {}
    raw = (qs or {}).get("limit") if isinstance(qs, dict) else None
    try:
        n = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(cap, n))


def _shape_history_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one v1 GetCustomerLoanHistory row → Recent Activity shape.

    v1 returns a mix of loan events (origination, payments, charges,
    refunds). The frontend renderer only cares about date / description /
    amount / direction / balance.
    """
    date = entry.get("TransactionDate") or entry.get("Date") or entry.get("EntryDate")
    amt = _to_number(
        entry.get("Amount")
        if entry.get("Amount") is not None
        else entry.get("TransactionAmount")
    )
    description = (
        entry.get("TransactionType")
        or entry.get("Description")
        or entry.get("Type")
        or "Activity"
    )
    # Direction: prefer explicit IsPayment flag, fall back to amount sign.
    is_payment = entry.get("IsPayment")
    if is_payment is None:
        direction = "credit" if (amt is not None and amt < 0) else "debit"
    else:
        direction = "credit" if is_payment else "debit"
    balance = _to_number(entry.get("RunningBalance") or entry.get("Balance"))
    if amt is None and not description:
        return None
    return {
        "date": _format_iso(date),
        "description": description,
        "amount": abs(amt) if amt is not None else None,
        "direction": direction,
        "balance": balance,
    }


def _fetch_loan_history(cid: str, hdr_id: Any, store_id: Any, limit: int) -> List[Dict[str, Any]]:
    """Call v1 /GetCustomerLoanHistory. Returns newest-first, trimmed to limit."""
    if not hdr_id:
        return []
    if _v1_user_id is None:
        # Prime the token (which also caches the user id).
        _get_v1_token()
    uid = _v1_user_id
    if uid is None:
        log.warning("v1 user id unavailable; skipping history")
        return []
    params = urllib.parse.urlencode({
        "custId": cid,
        "HdrId": hdr_id,
        "companyId": VERGENT_COMPANY_ID,
        "storeId": store_id or 0,
        "userId": uid,
    })
    status, body = _v1_get(f"/V1/GetCustomerLoanHistory?{params}")
    if status != 200:
        log.warning("GetCustomerLoanHistory status=%s", status)
        return []
    # Endpoint may return a list directly, or {Items: [...]}, or a dict with
    # transaction arrays by type. Normalize defensively.
    rows: List[Dict[str, Any]] = []
    if isinstance(body, list):
        rows = [r for r in body if isinstance(r, dict)]
    elif isinstance(body, dict):
        for key in ("Items", "Transactions", "History", "LoanHistory"):
            v = body.get(key)
            if isinstance(v, list):
                rows = [r for r in v if isinstance(r, dict)]
                break
        if not rows:
            # Fall through: flatten any top-level list values.
            for v in body.values():
                if isinstance(v, list):
                    rows.extend([r for r in v if isinstance(r, dict)])
    shaped = [s for s in (_shape_history_entry(r) for r in rows) if s]
    # Newest first.
    def _key(item: Dict[str, Any]) -> str:
        return str(item.get("date") or "")
    shaped.sort(key=_key, reverse=True)
    return shaped[:limit]


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"items": []})

    limit = _parse_limit(event, default=5)
    qs = event.get("queryStringParameters") or {}
    requested = (qs or {}).get("loanId") if isinstance(qs, dict) else None

    # Always fetch the customer's loans (open + closed) — gives us
    # ownership validation plus the storeId we need for
    # GetCustomerLoanHistory.
    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(200, {"items": []})

    if requested:
        loan = next(
            (l for l in shaped
             if str(l.get("id")) == str(requested)
             or str(l.get("publicId") or "") == str(requested)),
            None,
        )
        if not loan:
            return _json_response(404, {"error": "loan_not_found"})
    else:
        outstanding = [l for l in shaped if l.get("isOutstanding")]
        loan = outstanding[0] if outstanding else (shaped[0] if shaped else None)
        if not loan:
            return _json_response(200, {"items": []})

    items = _fetch_loan_history(cid, loan.get("id"), loan.get("storeId"), limit)
    return _json_response(200, {
        "items": items,
        "loanId": loan.get("id"),
        "publicId": loan.get("publicId"),
    })


def _shape_v1_document(record: Dict[str, Any], loan_id: Any, kind: str,
                       include_data: bool = False) -> Optional[Dict[str, Any]]:
    """Normalize one v1 document record from /customer/{id}/docs/loan/{hdr}.

    Vergent's loan-docs endpoint returns records like:
      { ChainId, HdrId, CustomerId, TransId, DocumentName,
        Data (base64 HTML), DocumentUrl (10-min Azure blob URL),
        DocType, DocTypeName, ... }

    We use ChainId as the unique id (Id/DocId/etc are not present).
    The Data field IS the document content — the listing endpoint
    inlines it. Download path re-fetches with include_data=True and
    streams Data straight back to the browser.

    Anything without an id is dropped.
    """
    if not isinstance(record, dict):
        return None
    doc_id = (
        record.get("ChainId")
        or record.get("Id") or record.get("id")
        or record.get("DocId") or record.get("docId")
        or record.get("DocumentId") or record.get("documentId")
    )
    if doc_id in (None, ""):
        return None
    fname = (
        record.get("DocumentName")
        or record.get("Filename") or record.get("FileName")
        or record.get("filename") or record.get("fileName")
        or record.get("Name") or record.get("name")
        or ""
    )
    title = (
        record.get("Title") or record.get("title")
        or record.get("DisplayName") or record.get("displayName")
        or fname
        or "Document"
    )
    # Strip extension from the display label for cleaner UI ("DDT
    # Disclosure" instead of "DDT Disclosure.html"). The fileName
    # keeps its extension for the download dialog.
    display = str(title)
    for ext in (".html", ".htm", ".pdf", ".aspx"):
        if display.lower().endswith(ext):
            display = display[: -len(ext)]
            break
    when = (
        record.get("DocumentDate") or record.get("documentDate")
        or record.get("Date") or record.get("date")
        or record.get("CreatedDate") or record.get("createdDate")
        or record.get("UploadDate") or record.get("uploadDate")
    )
    out = {
        "id": str(doc_id),
        "fileName": fname or (str(title) + ".html"),
        "displayName": display,
        "documentDate": _format_iso(when),
        "kind": kind,
        "loanId": loan_id,
    }
    if include_data:
        # Pass through fields the download path needs. _data is already
        # base64; we forward it verbatim with isBase64Encoded=true.
        out["_data"] = record.get("Data") or ""
        out["_docTypeName"] = (record.get("DocTypeName") or "").lower()
        out["_documentUrl"] = record.get("DocumentUrl") or ""
    return out


def _list_v1_loan_docs(cid: str, loan_id: Any,
                       include_data: bool = False) -> List[Dict[str, Any]]:
    """List signed documents attached to a specific loan via Vergent v1.

    Single endpoint: GET /V1/customer/{cid}/docs/loan/{loanId}. Verified
    against Harut's loan 4826490 — returns 3 signed records (Advance
    Receipt, DDT Disclosure, Advance Contract w E-Sign), each with its
    content base64-inlined as `Data`.

    With include_data=True, each shaped doc carries its raw Data +
    DocumentUrl for the download path to use.
    """
    if loan_id in (None, ""):
        return []

    out: List[Dict[str, Any]] = []
    seen: set = set()
    path = f"/V1/customer/{cid}/docs/loan/{loan_id}"
    status, body = _v1_get(path)

    rows: List[Dict[str, Any]] = []
    if status == 200:
        if isinstance(body, list):
            rows = [r for r in body if isinstance(r, dict)]
        elif isinstance(body, dict):
            for key in ("Items", "Documents", "Docs", "items", "documents", "docs"):
                v = body.get(key)
                if isinstance(v, list):
                    rows = [r for r in v if isinstance(r, dict)]
                    break

    for r in rows:
        shaped = _shape_v1_document(r, loan_id, "loan", include_data=include_data)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)

    if status not in (200, 404):
        log.warning("v1 loan-docs %s status=%s loan=%s", path, status, loan_id)

    # Newest first.
    def _key(item: Dict[str, Any]) -> str:
        return str(item.get("documentDate") or "")
    out.sort(key=_key, reverse=True)
    return out


def get_loan_documents(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"documents": []})

    qs = event.get("queryStringParameters") or {}
    requested = (qs or {}).get("loanId") if isinstance(qs, dict) else None
    if not requested:
        return _json_response(400, {"error": "missing_loanId"})

    # Validate ownership: the loanId must belong to this customer.
    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(200, {"documents": []})
    loan = next(
        (l for l in shaped
         if str(l.get("id")) == str(requested)
         or str(l.get("publicId") or "") == str(requested)),
        None,
    )
    if not loan:
        return _json_response(404, {"error": "loan_not_found"})

    docs = _list_v1_loan_docs(cid, loan.get("id"))
    return _json_response(200, {
        "documents": docs,
        "loanId": loan.get("id"),
        "publicId": loan.get("publicId"),
    })


def _render_html_to_pdf(html_b64: str, file_name: str) -> Optional[bytes]:
    """Invoke the doc-pdf Lambda to render HTML → PDF. Returns the
    raw PDF bytes on success, or None on any failure (caller falls
    back to serving HTML)."""
    import base64
    if not DOC_PDF_FN_NAME:
        log.warning("DOC_PDF_FN_NAME not set; skipping PDF render")
        return None
    try:
        html = base64.b64decode(html_b64).decode("utf-8", "replace")
    except Exception as exc:
        log.warning("doc-pdf decode failed: %s", exc)
        return None
    try:
        resp = _lambda_client.invoke(
            FunctionName=DOC_PDF_FN_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps({"html": html, "fileName": file_name}).encode("utf-8"),
        )
    except ClientError as exc:
        log.warning("doc-pdf invoke failed: %s", exc.response.get("Error", {}).get("Code"))
        return None
    except Exception as exc:
        log.warning("doc-pdf invoke unexpected: %s", exc)
        return None

    payload_bytes = resp.get("Payload").read() if resp.get("Payload") else b""
    if resp.get("FunctionError"):
        log.warning("doc-pdf returned FunctionError; payload=%s",
                    payload_bytes[:200].decode("utf-8", "replace"))
        return None
    try:
        result = json.loads(payload_bytes.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    if not result.get("ok"):
        log.warning("doc-pdf result not ok: %s", result.get("error") or result.get("detail") or "?")
        return None
    pdf_b64 = result.get("pdfBase64") or ""
    if not pdf_b64:
        return None
    try:
        return base64.b64decode(pdf_b64)
    except Exception:
        return None


def get_document_download(event: Dict[str, Any]) -> Dict[str, Any]:
    """Stream a single document back to the browser.

    Ownership: only docs found via the customer's own loans are
    eligible. We list every loan's docs and confirm the requested
    docId is in that set before fetching from Vergent.

    `?format=pdf` invokes the doc-pdf Lambda (Node.js + headless
    Chromium) to convert Vergent's HTML to a real PDF before
    serving it. Without that param, the original HTML is served
    so the in-page modal can render it.
    """
    import base64

    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    # docId can come from API Gateway pathParameters or by parsing the path.
    doc_id = None
    pp = event.get("pathParameters") or {}
    if isinstance(pp, dict):
        doc_id = pp.get("docId") or pp.get("documentId")
    if not doc_id:
        path = (event.get("requestContext") or {}).get("http", {}).get("path", "")
        # Expect: /api/my-loans/documents/{docId}/download
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 4 and parts[-1] == "download" and parts[-3] == "documents":
            doc_id = parts[-2]
    if not doc_id:
        return _json_response(400, {"error": "missing_docId"})

    qs = event.get("queryStringParameters") or {}
    want_pdf = (qs or {}).get("format") == "pdf"

    # Ownership check + content fetch: walk this customer's loans and
    # find the matching docId. Vergent's listing endpoint inlines the
    # document content as base64 in the `Data` field, so a single
    # listing call gets us both ownership confirmation AND the content
    # — no separate binary download endpoint needed.
    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(404, {"error": "doc_not_found"})
    matched = None
    for loan in shaped:
        docs = _list_v1_loan_docs(cid, loan.get("id"), include_data=True)
        for d in docs:
            if str(d.get("id")) == str(doc_id):
                matched = d
                break
        if matched:
            break
    if not matched:
        log.warning("doc-download not-owned cust=%s doc=%s", cid, doc_id)
        return _json_response(404, {"error": "doc_not_found"})

    data_b64 = matched.get("_data") or ""
    if not data_b64:
        # Fallback: redirect to the short-lived Azure blob URL Vergent
        # provides. Used only if Data was empty (rare).
        url = matched.get("_documentUrl") or ""
        if url:
            return {
                "statusCode": 302,
                "headers": {**CORS_HEADERS, "Location": url, "Cache-Control": "no-store"},
                "body": "",
            }
        log.warning("doc-download no-data cust=%s doc=%s", cid, doc_id)
        return _json_response(502, {"error": "doc_unavailable"})

    # Content type from Vergent's DocTypeName (e.g. "aspx" -> html).
    type_name = matched.get("_docTypeName") or ""
    if type_name in ("html", "htm", "aspx"):
        content_type = "text/html; charset=utf-8"
    elif type_name == "pdf":
        content_type = "application/pdf"
    elif type_name in ("png", "jpg", "jpeg", "gif"):
        content_type = f"image/{'jpeg' if type_name == 'jpg' else type_name}"
    else:
        content_type = "application/octet-stream"

    fname_base = matched.get("fileName") or f"document-{doc_id}.html"
    fname_base = fname_base.replace("/", "_").replace("\\", "_").replace('"', "")

    # PDF path: only meaningful when the source is HTML/aspx. For PDFs
    # already, just stream the original (no conversion needed).
    # If conversion fails, return 502 explicitly — falling through to
    # HTML response with the customer's frontend expecting a PDF would
    # save HTML content as a .pdf file, which fails to open. The
    # frontend handles the 502 by retrying without ?format=pdf.
    if want_pdf and type_name in ("html", "htm", "aspx"):
        pdf_bytes = _render_html_to_pdf(data_b64, fname_base)
        if pdf_bytes:
            pdf_fname = fname_base.rsplit(".", 1)[0] + ".pdf"
            return {
                "statusCode": 200,
                "headers": {
                    **CORS_HEADERS,
                    "Content-Type": "application/pdf",
                    "Content-Disposition": f'inline; filename="{pdf_fname}"',
                    "Cache-Control": "private, max-age=60",
                },
                "isBase64Encoded": True,
                "body": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        log.warning("doc-pdf render failed cust=%s doc=%s", cid, doc_id)
        return _json_response(502, {"error": "pdf_render_failed"})

    return {
        "statusCode": 200,
        "headers": {
            **CORS_HEADERS,
            "Content-Type": content_type,
            "Content-Disposition": f'inline; filename="{fname_base}"',
            "Cache-Control": "private, max-age=60",
        },
        "isBase64Encoded": True,
        "body": data_b64,  # Vergent already base64-encodes Data
    }


def request_new_loan_handoff(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(400, {"error": "no_customer_id"})

    tok = _get_apim_token()
    if not tok:
        return _json_response(502, {"error": "apim_unavailable"})
    creds = _get_creds()
    status, body, _raw = _http(
        f"{APIM_BASE}/api/authenticate/handoff/create",
        "POST",
        body={
            "customerId": int(cid),
            "TargetRelativePage": "/",
            "ExpectedReferrerAuthority": HANDOFF_AUTHORITY,
        },
        headers={"x-api-key": creds["xApiKey"], "Authorization": f"Bearer {tok}"},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("handoff/create failed status=%s", status)
        return _json_response(502, {"error": "handoff_failed"})

    url = body.get("handoffUrl") or body.get("handoff_url")
    token = body.get("token")
    if not url:
        return _json_response(502, {"error": "handoff_no_url"})
    return _json_response(200, {"url": url, "token": token})


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

        if path.endswith("/my-profile") and method == "GET":
            return get_my_profile(event)
        if path.endswith("/my-profile/email") and method == "PUT":
            return update_email(event)
        if path.endswith("/my-profile/address") and method == "PUT":
            return update_address(event)
        if path.endswith("/my-profile/phone/start-verify") and method == "POST":
            return start_phone_verify(event)
        if path.endswith("/my-profile/phone/confirm") and method == "POST":
            return confirm_phone_verify(event)
        if path.endswith("/my-loan/new") and method == "POST":
            return request_new_loan_handoff(event)
        if path.endswith("/my-loans/active") and method == "GET":
            return get_active_loan(event)
        if path.endswith("/my-loans/activity") and method == "GET":
            return get_activity(event)
        if path.endswith("/my-loans/documents") and method == "GET":
            return get_loan_documents(event)
        # /api/my-loans/documents/{docId}/download
        if (path.endswith("/download")
                and "/my-loans/documents/" in path
                and method == "GET"):
            return get_document_download(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("loans handler unexpected error: %s", exc)
        return _json_response(200, {"error": "upstream_unavailable"})
