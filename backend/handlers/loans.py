"""
Customer Portal - Account + Loans handler (Vergent v1 LMS API).

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-profile       -> profile card data
  GET  /api/my-loans/active  -> active loan with balance / due date / status
  GET  /api/my-loans/activity -> recent activity (empty until loan/transactions wired)
  GET  /api/my-loans/documents -> list signed documents for ?loanId=X
  GET  /api/my-loans/documents/{docId}/download -> stream document binary
  POST /api/my-loan/new      -> returns handoff URL into Vergent loan-application UI

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
from typing import Any, Dict, List, Optional, Tuple

import boto3

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
DOC_PDF_FN_NAME = os.environ.get("DOC_PDF_FN_NAME", "")  # set by provision-doc-pdf.yml
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

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Cache-Control": "no-store",
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


def _v1_get_binary(path: str, timeout: int = 20) -> Tuple[int, bytes, Dict[str, str]]:
    """GET a v1 endpoint that returns binary (e.g. /docs/{id}/download).

    Returns (status, body_bytes, response_headers). On failure returns
    (status, b"", {}). Refreshes service token once on 401/403.
    """
    def _attempt(tok: str) -> Tuple[int, bytes, Dict[str, str]]:
        req = urllib.request.Request(
            f"{V1_BASE}{path}",
            method="GET",
            headers={
                "Token": tok,
                "Accept": "*/*",
                "User-Agent": "cif-portal/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            try:
                _ = e.read()  # drain
            except Exception:
                pass
            log.warning("v1 binary GET %s -> %s", path, e.code)
            return e.code, b"", {}
        except (urllib.error.URLError, TimeoutError) as exc:
            log.error("v1 binary GET %s network: %s", path, exc)
            return 0, b"", {}

    token = _get_v1_token()
    if not token:
        return 0, b"", {}
    status, body, headers = _attempt(token)
    if status in (401, 403):
        global _v1_token_exp
        _v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, body, headers = _attempt(tok2)
    return status, body, headers


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
    if log.isEnabledFor(logging.INFO):
        # One-shot full inventory — we need to see every field Vergent
        # actually returns so we can pick the right autopay-indicator.
        # Remove this once autopay is wired correctly.
        log.info("autopay probe hdr_id=%s hdr_keys=%s detail_keys=%s",
                 hdr.get("hdr_id"),
                 sorted(hdr.keys()) if isinstance(hdr, dict) else None,
                 sorted(detail.keys()) if isinstance(detail, dict) else None)
        # Status probe — figure out which Vergent field carries the
        # admin-UI "Paid Off" vs "Deleted" distinction so we can
        # tighten _is_visible_loan precisely.
        log.info("loan-status probe hdr_id=%s isOutstanding=%s statusId=%s "
                 "Status=%r SubStatus=%r",
                 hdr.get("hdr_id"), is_outstanding, status_id,
                 hdr.get("Status"), hdr.get("SubStatus"))

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
            visible = [l for l in shaped if _is_visible_loan(l)]
            log.info("v1 loans served by %s raw=%d visible=%d", path, len(shaped), len(visible))
            return visible
        log.info("v1 loans %s status=%s", path, status)
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

    # v1 customer data — includes addresses + phones with masked numbers
    status2, data = _v1_get(f"/V1/GetCustomerData/{cid}")
    if status2 == 200 and isinstance(data, dict):
        phones = data.get("custPhones") or []
        if isinstance(phones, list) and phones:
            # v1 returns snake_case keys: is_primary, number, type_name.
            primary_phone = next(
                (p for p in phones if isinstance(p, dict) and p.get("is_primary")),
                phones[0] if isinstance(phones[0], dict) else None,
            )
            if primary_phone:
                profile["vergentPhoneHint"] = _mask_phone(primary_phone.get("number"))

    return _json_response(200, profile)


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
                       debug: bool = False,
                       include_data: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """List signed documents attached to a specific loan via Vergent v1.

    Single endpoint: GET /V1/customer/{cid}/docs/loan/{loanId}. Verified
    2026-05-01 against Harut's loan 4826490 — returns 3 signed records
    (Advance Receipt, DDT Disclosure, Advance Contract w E-Sign), each
    with its content base64-inlined as `Data`. The OtherFiles sibling,
    PascalCase variants, verb-style endpoints, and customer-level dump
    were all tested and either return duplicates or 404 — dropped.

    Returns (shaped_docs, attempts). `attempts` is populated only when
    debug=True for diagnostics. With include_data=True, each shaped doc
    carries its raw Data + DocumentUrl for the download path to use.
    """
    if loan_id in (None, ""):
        return [], []

    out: List[Dict[str, Any]] = []
    seen: set = set()
    attempts: List[Dict[str, Any]] = []
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

    kept = 0
    for r in rows:
        shaped = _shape_v1_document(r, loan_id, "loan", include_data=include_data)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)
        kept += 1

    if debug:
        # Cap the preview so we don't blow up the response when content
        # is base64-inlined. Strip Data field from previews.
        def _strip(rec: Any) -> Any:
            if isinstance(rec, dict):
                return {k: ("<...>" if k == "Data" else v) for k, v in rec.items()}
            return rec
        preview = body
        if isinstance(body, list):
            preview = [_strip(r) for r in body[:3]]
        elif isinstance(body, dict):
            preview = {k: v for k, v in list(body.items())[:8]}
        attempts.append({
            "path": path, "status": status, "rows": len(rows),
            "kept": kept, "preview": preview,
        })
    if status not in (200, 404):
        log.warning("v1 loan-docs %s status=%s loan=%s", path, status, loan_id)

    # Newest first.
    def _key(item: Dict[str, Any]) -> str:
        return str(item.get("documentDate") or "")
    out.sort(key=_key, reverse=True)
    return out, attempts


def get_loan_documents(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"documents": []})

    qs = event.get("queryStringParameters") or {}
    requested = (qs or {}).get("loanId") if isinstance(qs, dict) else None
    debug = (qs or {}).get("debug") == "1"
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

    docs, attempts = _list_v1_loan_docs(cid, loan.get("id"), debug=debug)
    response = {
        "documents": docs,
        "loanId": loan.get("id"),
        "publicId": loan.get("publicId"),
    }
    if debug:
        response["_debug"] = {
            "cid": cid,
            "requestedLoanId": requested,
            "matchedLoan": {
                "id": loan.get("id"),
                "publicId": loan.get("publicId"),
                "status": loan.get("status"),
                "statusId": loan.get("statusId"),
            },
            "attempts": attempts,
        }
    return _json_response(200, response)


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
        docs, _ = _list_v1_loan_docs(cid, loan.get("id"), include_data=True)
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
    # already, just stream the original. For everything else, fall back
    # to the original content too — we only convert HTML.
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
        # PDF render failed — fall through and serve HTML so the user
        # still gets *something* rather than an error.
        log.warning("doc-pdf render failed; falling back to HTML cust=%s doc=%s", cid, doc_id)

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
