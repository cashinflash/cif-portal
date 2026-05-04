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

import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets_module  # avoid clash with `_secrets` boto client
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# Telnyx Verify — used for SMS-PIN flow on profile-page phone
# changes. Same module that powers login MFA in auth_mfa.py.
from handlers import telnyx_verify

# Resend transactional email — replaced AWS SES after AWS denied
# production access twice. Both admin notifications and customer
# change-request confirmations route through it.
from handlers import resend_email

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
_cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
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

    # Fee amount — Vergent uses different field names across products
    # and lifecycle stages. On a PAID-OFF loan, "current" fee fields
    # (e.g. `Fees`) return 0 because nothing is currently owing.
    # Search:
    #   1. Original* prefixed fields (accept zero — explicit value).
    #   2. General fee names (skip zero — likely a "currently owing"
    #      value, misleading after payoff).
    #   3. payoff/amount-due minus principal — only useful for
    #      outstanding loans.
    # If still null on a paid-off loan, the route handler patches it
    # from peak Balance in the transaction history (see
    # _patch_missing_fees).
    fees = None
    ORIGINAL_FEE_KEYS = (
        "OriginalFees", "OriginalFeeAmount", "OriginalFinanceCharge",
        "OriginalCharges", "OriginalCharge",
    )
    OTHER_FEE_KEYS = (
        "Fees", "LoanFees", "FeeAmount", "FinanceCharge", "TotalFees",
        "TotalFinanceCharge", "FeesTotal", "TotalCharge",
    )

    def _try_keys(source: Dict[str, Any], keys, accept_zero: bool) -> Optional[float]:
        for k in keys:
            v = source.get(k)
            if v is None:
                continue
            n = _to_number(v)
            if n is None:
                continue
            if n == 0 and not accept_zero:
                continue
            return n
        return None

    fees = _try_keys(hdr, ORIGINAL_FEE_KEYS, accept_zero=True)
    if fees is None and isinstance(detail, dict):
        fees = _try_keys(detail, ORIGINAL_FEE_KEYS, accept_zero=True)
    if fees is None:
        fees = _try_keys(hdr, OTHER_FEE_KEYS, accept_zero=False)
    if fees is None and isinstance(detail, dict):
        fees = _try_keys(detail, OTHER_FEE_KEYS, accept_zero=False)
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


def _patch_missing_fees(cid: str, loans: List[Dict[str, Any]]) -> None:
    """For loans where `fees` couldn't be extracted from the loan-list
    response (typically paid-off loans where Vergent returns only
    0-valued "currently owing" fee fields), derive the originated fee
    from the peak running Balance across the loan's transaction
    history:

        fees = max(Balance) - principal

    Vergent's transaction records carry separate `Prin`, `Fee`,
    `Total`, and `Balance` columns; `Balance` is the post-transaction
    running balance. The peak balance is reached right after the
    Advance + Advance Fee transactions are posted, so it equals
    principal + total fees ever charged. Subtracting principal
    yields the originated fee, regardless of how the loan was
    eventually repaid. (Backup: sum of positive `Fee` column values
    — used only if the Balance column is absent on some product.)

    Mutates the list in place. Best-effort — failures (network,
    unexpected shape, etc.) leave fees=null and the UI just shows "—".
    Each missing-fee loan triggers one extra v1 GetCustomerLoanHistory
    call, which is fine for the typical CIF customer with 1-3 loans.
    """
    for loan in loans:
        if loan.get("fees") is not None:
            continue
        principal = _to_number(loan.get("principal"))
        hdr_id = loan.get("id")
        store_id = loan.get("storeId")
        if not principal or not hdr_id or principal <= 0:
            continue

        # Direct raw v1 call — Vergent's transactions store the fee
        # under a `Fee` column distinct from `Amount`, and the running
        # balance is in `Balance`. Peak balance = principal + total
        # fees, so we derive fees from that. Works for any loan type
        # without needing to know which "Type" string is the fee row.
        if _v1_user_id is None:
            _get_v1_token()
        uid = _v1_user_id or 0
        params = urllib.parse.urlencode({
            "custId": cid,
            "HdrId": hdr_id,
            "companyId": VERGENT_COMPANY_ID,
            "storeId": store_id or 0,
            "userId": uid,
        })
        try:
            status, body = _v1_get(f"/V1/GetCustomerLoanHistory?{params}")
        except Exception as e:
            log.warning("patch-fees history error hdr_id=%s err=%s",
                        hdr_id, type(e).__name__)
            continue
        if status != 200:
            continue
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
            continue

        # Max Balance across all non-voided rows = principal + total
        # fees ever charged. Excludes voided transactions so we don't
        # count them.
        max_balance = 0.0
        fee_sum = 0.0
        for r in rows:
            if r.get("IsVoid"):
                continue
            bal = _to_number(r.get("Balance"))
            if bal is not None and bal > max_balance:
                max_balance = bal
            # Backup: sum the Fee column on rows where it's positive.
            fee = _to_number(r.get("Fee"))
            if fee is not None and fee > 0:
                fee_sum += fee

        derived_fee: Optional[float] = None
        if max_balance > principal:
            derived_fee = round(max_balance - principal, 2)
        elif fee_sum > 0:
            derived_fee = round(fee_sum, 2)

        if derived_fee is not None:
            loan["fees"] = derived_fee
            log.info("patched fees hdr_id=%s max_balance=%.2f fee_sum=%.2f principal=%.2f fees=%.2f",
                     hdr_id, max_balance, fee_sum, principal, derived_fee)


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def _maybe_sync_cognito_email(claims: Dict[str, Any], vergent_email: Optional[str]) -> None:
    """If the customer's Vergent email differs from their Cognito email,
    update Cognito so they can sign in with the new email next time.

    Vergent is the system of record. When an admin changes the email
    in Vergent admin, the next /api/my-profile call from the customer
    triggers this sync — they continue using their old email for the
    current session, then sign in next time with the new email.

    Best-effort: failures log but never propagate to the customer.
    Email is an alias attribute in our user pool (username = sub),
    so updating the email attribute makes the new value the valid
    sign-in alias.
    """
    if not COGNITO_USER_POOL_ID:
        return
    cognito_email = (claims.get("email") or "").strip().lower()
    new_email = (vergent_email or "").strip().lower()
    if not new_email or cognito_email == new_email:
        return
    sub = claims.get("sub") or claims.get("cognito:username")
    if not sub:
        return
    try:
        _cognito.admin_update_user_attributes(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=sub,
            UserAttributes=[
                {"Name": "email", "Value": new_email},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        log.info("cognito email synced sub=%s old=%s new=%s",
                 sub, _mask_email(cognito_email), _mask_email(new_email))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        # AliasExistsException = the new email is already used by
        # another Cognito user (rare; would require two CIF customers
        # to share an email at Vergent). Log and move on.
        log.warning("cognito email sync failed code=%s sub=%s", code, sub)
    except Exception as e:
        log.warning("cognito email sync unexpected: %s", type(e).__name__)


def _mask_email(e: str) -> str:
    if not e or "@" not in e:
        return "***"
    name, _, dom = e.partition("@")
    if len(name) <= 2:
        return "***@" + dom
    return name[0] + "***" + name[-1] + "@" + dom


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

    # Sync Cognito email to match Vergent if they've diverged. This
    # is what makes admin email changes in Vergent flow through to
    # the customer's sign-in email — without this, the customer keeps
    # signing in with their old email forever.
    _maybe_sync_cognito_email(claims, profile.get("vergentEmail"))

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

    ok, err_code, err_msg = resend_email.send(
        to=ADMIN_NOTIFY_EMAIL,
        subject=subject,
        text=body_text,
        html=body_html,
    )
    if not ok:
        log.warning("admin notification send failed code=%s msg=%s",
                    err_code, (err_msg or "")[:200])


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

    subject = f"We received your request to update your {field_label}"

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
        f'<tr><td style="padding:14px 18px;color:#6b7280;width:120px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;font-weight:600;">Requested</td>'
        f'<td style="padding:14px 18px 14px 0;color:#1a1a2e;font-size:15px;font-weight:600;line-height:1.45;">{requested_display}</td></tr>'
    ) if requested_display else ""

    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,'SF Pro Text','Segoe UI',Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:36px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:36px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Account update received</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">We've got your request, {first_name}.</h1>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#1a1a2e;">We've received your request to update the <strong>{field_label}</strong> on your Cash in Flash account.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#f9fafb;border-radius:10px;">
            {requested_row}
          </table>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#1a1a2e;">For your security, this change is reviewed by a Cash in Flash specialist before it takes effect — usually within <strong>one business day</strong>. We'll email you once it's applied.</p>
          <p style="margin:0 0 4px;font-size:13px;line-height:1.6;color:#6b7280;">Didn't request this? Call us right away at <a href="tel:+17472707121" style="color:#0E8741;font-weight:600;text-decoration:none;">(747) 270-7121</a>.</p>
        </td></tr>
        <tr><td style="padding:22px 36px 32px;border-top:1px solid #e5e7eb;background:#fafafa;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 6px;">Cash in Flash &middot; Licensed by the California Department of Financial Protection and Innovation #214840</p>
          <p style="margin:0;">This email was sent by Cash in Flash &middot; 13937B Van Nuys Blvd, Arleta, CA 91331. Please do not reply to this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    ok, err_code, err_msg = resend_email.send(
        to=customer_email,
        subject=subject,
        text=body_text,
        html=body_html,
    )
    if not ok:
        log.warning("customer confirmation send failed code=%s msg=%s",
                    err_code, (err_msg or "")[:200])


def _hash_code(code: str) -> str:
    """SHA-256 hex digest of a verification code, used for safe storage."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """Six-digit numeric code suitable for an SMS/email OTP."""
    return f"{_secrets_module.randbelow(1_000_000):06d}"


def _send_email_verify_code(to_email: str, code: str) -> Tuple[bool, str]:
    """Send a 6-digit verification code via Resend to a candidate new
    email address. Used by the profile email-change flow before the
    request lands in the admin queue."""
    text = (
        f"Your verification code is {code}.\n\n"
        f"This code lets us confirm you have access to {to_email} "
        f"before our team applies the change to your Cash in Flash account. "
        f"It expires in 10 minutes.\n\n"
        f"If you didn't request this, you can safely ignore this email "
        f"or call us at (747) 270-7121.\n\n"
        f"---\n"
        f"Cash in Flash · Licensed by the California Department of "
        f"Financial Protection and Innovation #214840\n"
        f"This is an automated message. Please do not reply.\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:32px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:32px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:32px 36px 8px;">
          <p style="margin:0 0 8px;font-size:13px;color:#6b7280;letter-spacing:.06em;text-transform:uppercase;font-weight:600;">Verification code</p>
          <h1 style="margin:0 0 18px;font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;">{code}</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:#1a1a2e;">Enter this code in your account profile to confirm <strong>{to_email}</strong>.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#6b7280;">This code expires in <strong>10 minutes</strong>. If you didn't request this change, you can safely ignore this email or call us at <a href="tel:+17472707121" style="color:#0E8741;text-decoration:none;font-weight:600;">(747) 270-7121</a>.</p>
        </td></tr>
        <tr><td style="padding:18px 36px 28px;border-top:1px solid #e5e7eb;background:#fafafa;color:#6b7280;font-size:11px;line-height:1.5;">
          Cash in Flash &middot; Licensed by the California Department of Financial Protection and Innovation #214840<br>
          This is an automated message. Please do not reply to this email.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    ok, err_code, err_msg = resend_email.send(
        to=to_email,
        subject="Your verification code",
        text=text,
        html=html,
    )
    if not ok:
        log.warning("email-verify code send failed code=%s msg=%s",
                    err_code, (err_msg or "")[:200])
        return False, err_code or "send_failed"
    return True, ""


def start_email_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-profile/email/start-verify — kick off the
    email-change flow by texting (well, emailing) a 6-digit code to
    the candidate new address. The customer enters the code in the
    next step (`confirm_email_verify`) before the request lands in
    the admin queue.

    This is the security boundary that keeps a stolen session from
    pivoting to email-takeover by changing the contact email.
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

    # Don't waste a code if it's the same as what's already on file.
    current_email = ""
    status, prof = _v1_get(f"/V1/GetCustomer/{cid}")
    if status == 200 and isinstance(prof, dict):
        current_email = (prof.get("EmailAddr") or "").strip()
    if current_email and current_email.lower() == new_email:
        return _json_response(400, {"error": "no_change"})

    # Generate + store verification session in the existing
    # profile-change-requests DDB table. status='awaiting_email_verify'
    # so the admin queue ignores it; TTL 10 min so abandoned sessions
    # self-delete. On confirm we flip status to 'pending' and fire
    # the admin/customer notifications.
    code = _generate_code()
    code_hash = _hash_code(code)
    request_id = str(uuid.uuid4())
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    expires_at = int(time.time()) + 10 * 60  # 10-min TTL
    item = {
        "requestId":         {"S": request_id},
        "customerId":        {"S": str(cid)},
        "field":             {"S": "email"},
        "currentValue":      {"S": current_email or ""},
        "requestedValue":    {"S": new_email},
        "status":            {"S": "awaiting_email_verify"},
        "codeHash":          {"S": code_hash},
        "attempts":          {"N": "0"},
        "requestedAt":       {"S": now_iso},
        "requestedByEmail":  {"S": (claims.get("email") or "").strip()},
        "expiresAt":         {"N": str(expires_at)},
    }
    try:
        _dynamo.put_item(TableName=PROFILE_REQUESTS_TABLE, Item=item)
    except ClientError as e:
        log.error("DDB put for email-verify failed: %s",
                  e.response.get("Error", {}).get("Code"))
        return _json_response(502, {"error": "queue_unavailable"})

    sent_ok, sent_err = _send_email_verify_code(new_email, code)
    if not sent_ok:
        # Best-effort cleanup so a failed send doesn't leave a
        # dangling session row.
        try:
            _dynamo.delete_item(TableName=PROFILE_REQUESTS_TABLE,
                                Key={"requestId": {"S": request_id}})
        except Exception:
            pass
        return _json_response(502, {"error": "send_failed", "detail": sent_err})

    return _json_response(200, {
        "ok": True,
        "requestId": request_id,
        "maskedEmail": _mask_email(new_email),
    })


def _push_email_to_vergent(cid: str, new_email: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Best-effort attempt to update the customer's email in Vergent
    after we've verified the customer owns the new address. Returns
    (ok, attempts) where attempts is a list of dicts describing each
    step we ran — used for DDB diagnostic logging so future failures
    are easy to debug without redeploying.

    Vergent's PutCustomer endpoint expects the FULL customer record;
    sending just `{id, EmailAddr}` is rejected with a 400 because
    other required fields (FirstName, BirthDate, etc.) come back
    null. So this is a read-modify-write: GET the current record,
    mutate EmailAddr only, PUT it back.

    Falls through to the admin-queue path on any error.
    """
    try:
        cid_int = int(cid)
    except (TypeError, ValueError):
        return False, [{"error": "bad_cid", "cid": str(cid)}]

    attempts: List[Dict[str, Any]] = []

    # Step 1: read the full current customer record.
    get_status, current = _v1_get(f"/V1/GetCustomer/{cid_int}")
    attempts.append({
        "step": "get",
        "method": "GET",
        "path": f"/V1/GetCustomer/{cid_int}",
        "status": get_status,
    })
    if get_status != 200 or not isinstance(current, dict):
        log.warning("vergent push-email get-customer failed status=%s cid=%s",
                    get_status, cid)
        return False, attempts

    # Step 2: mutate just the EmailAddr field; keep every other field
    # at its current value. Vergent likely also expects EmailAddr to
    # be lowercase/normalized — we already store the verified value
    # that way upstream.
    body = dict(current)
    body["EmailAddr"] = new_email

    # Step 3: PUT the full record back.
    put_status, _resp, raw = _v1_request(
        "PUT", f"/V1/PutCustomer/{cid_int}",
        body=body, return_raw=True,
    )
    snippet = (raw or "")[:300]
    attempts.append({
        "step": "put",
        "method": "PUT",
        "path": f"/V1/PutCustomer/{cid_int}",
        "status": put_status,
        "snippet": snippet,
    })
    log.info("vergent push-email put status=%s cid=%s body=%s",
             put_status, cid, snippet)
    return put_status in (200, 204), attempts


def _send_email_applied_alert(claims: Dict[str, Any], new_email: str) -> None:
    """Customer-facing email sent after a successful auto-applied
    email change. Different copy from the queued/pending notification
    — this one says 'your new email is now active.'"""
    if not new_email:
        return
    first_name = (claims.get("given_name") or "").strip() or "there"
    when = _format_pacific_time(datetime.utcnow())

    text = (
        f"Hi {first_name},\n\n"
        f"Your Cash in Flash account email is now {new_email}, effective {when}.\n\n"
        f"Future account notices, sign-in codes, and statements will be "
        f"delivered here. There's nothing else you need to do.\n\n"
        f"If you didn't make this change, please call us right away at "
        f"(747) 270-7121 so we can secure your account.\n\n"
        f"---\n"
        f"Cash in Flash · Licensed by the California Department of "
        f"Financial Protection and Innovation #214840\n"
        f"This is an automated security notification. Please do not reply.\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,'SF Pro Text','Segoe UI',Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:36px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:36px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Email updated</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">Your email address is now active.</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">Hi {first_name}, your Cash in Flash account email is now <strong>{new_email}</strong>, effective {when}.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#1a1a2e;">Future account notices, sign-in codes, and statements will be delivered here. There's nothing else you need to do.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#fef3f2;border-radius:10px;border-left:4px solid #dc2626;">
            <tr><td style="padding:14px 18px;color:#991b1b;font-size:14px;line-height:1.55;">
              <strong>Didn't make this change?</strong> Call us right away at <a href="tel:+17472707121" style="color:#991b1b;font-weight:700;text-decoration:underline;">(747) 270-7121</a> and we'll secure your account.
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:22px 36px 32px;border-top:1px solid #e5e7eb;background:#fafafa;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 6px;">Cash in Flash &middot; Licensed by the California Department of Financial Protection and Innovation #214840</p>
          <p style="margin:0;">This email was sent by Cash in Flash &middot; 13937B Van Nuys Blvd, Arleta, CA 91331. Please do not reply to this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    ok, err_code, err_msg = resend_email.send(
        to=new_email,
        subject="Your email address is now active",
        text=text,
        html=html,
    )
    if not ok:
        log.warning("email-applied alert send failed code=%s msg=%s",
                    err_code, (err_msg or "")[:200])


def confirm_email_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-profile/email/confirm — verify the 6-digit code
    we sent to the candidate new email, then flip the queued row to
    `status=pending` and fire the admin + customer notification
    emails. Same end state as the old single-shot update_email but
    with proven control over the new email."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    request_id = (body.get("requestId") or "").strip()
    code = _digits_only(body.get("code") or "")
    if not request_id or not code:
        return _json_response(400, {"error": "missing_fields"})

    try:
        resp = _dynamo.get_item(
            TableName=PROFILE_REQUESTS_TABLE,
            Key={"requestId": {"S": request_id}},
        )
    except ClientError as e:
        log.error("DDB get for email-verify failed: %s",
                  e.response.get("Error", {}).get("Code"))
        return _json_response(502, {"error": "queue_unavailable"})
    item = resp.get("Item") or {}
    if not item:
        return _json_response(400, {"error": "session_expired"})

    # Belt-and-suspenders: confirm row belongs to this customer + is
    # in the right state and not expired.
    if item.get("customerId", {}).get("S") != str(cid):
        return _json_response(403, {"error": "forbidden"})
    if item.get("status", {}).get("S") != "awaiting_email_verify":
        return _json_response(400, {"error": "session_state"})
    if int(item.get("expiresAt", {}).get("N", "0")) <= int(time.time()):
        return _json_response(400, {"error": "session_expired"})

    attempts = int(item.get("attempts", {}).get("N", "0"))
    if attempts >= 5:
        # Lock out further attempts; the row still TTL-deletes.
        return _json_response(400, {"error": "too_many_attempts"})

    expected_hash = item.get("codeHash", {}).get("S", "")
    actual_hash = _hash_code(code)
    if not expected_hash or not hmac.compare_digest(expected_hash, actual_hash):
        try:
            _dynamo.update_item(
                TableName=PROFILE_REQUESTS_TABLE,
                Key={"requestId": {"S": request_id}},
                UpdateExpression="SET attempts = :a",
                ExpressionAttributeValues={":a": {"N": str(attempts + 1)}},
            )
        except Exception:
            pass
        return _json_response(400, {"error": "code_invalid"})

    # Code matches. Try to push to Vergent directly — if it accepts,
    # the change is live immediately. If it rejects, fall back to the
    # admin-queue path so an admin can apply manually. Customer is
    # safe either way: they've already proven control of the new email.
    new_email = item.get("requestedValue", {}).get("S", "")
    current_email = item.get("currentValue", {}).get("S", "") or None
    long_ttl = int(time.time()) + 90 * 24 * 60 * 60  # 90-day audit retention

    pushed_ok, push_attempts = _push_email_to_vergent(str(cid), new_email)
    final_status = "applied_auto" if pushed_ok else "pending"
    last_attempt = push_attempts[-1] if push_attempts else {}
    meta: Dict[str, Any] = {
        "emailVerified": True,
        # Backward-compatible single-attempt fields (last attempt wins).
        "vergentPushStatus": last_attempt.get("status", 0),
        # Full audit trail: which paths were tried and what each said.
        "vergentPushAttempts": push_attempts,
    }
    if not pushed_ok and last_attempt.get("snippet"):
        meta["vergentPushBody"] = last_attempt["snippet"][:200]

    try:
        _dynamo.update_item(
            TableName=PROFILE_REQUESTS_TABLE,
            Key={"requestId": {"S": request_id}},
            UpdateExpression=(
                "SET #s = :s, expiresAt = :e, "
                "meta = :meta REMOVE codeHash, attempts"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": {"S": final_status},
                ":e": {"N": str(long_ttl)},
                ":meta": {"S": json.dumps(meta, default=str)},
            },
        )
    except ClientError as e:
        log.error("DDB promote for email-verify failed: %s",
                  e.response.get("Error", {}).get("Code"))
        return _json_response(502, {"error": "queue_unavailable"})

    if pushed_ok:
        # Auto-apply succeeded — sync Cognito immediately so the new
        # email becomes the valid sign-in alias right away (Phase H
        # would otherwise wait until the next /api/my-profile call).
        _maybe_sync_cognito_email(claims, new_email)
        # Customer-facing "your email is now active" alert. No admin
        # email — there's nothing for them to do.
        _send_email_applied_alert(claims, new_email)
        log.info("email auto-applied cid=%s old=%s new=%s",
                 cid, _mask_email(current_email or ""), _mask_email(new_email))
        return _json_response(200, {"ok": True, "status": "applied"})

    # Vergent rejected the push — fall back to the existing admin
    # queue flow so a human can apply it.
    log.warning("vergent push failed last_status=%s attempts=%d falling back to admin queue cid=%s",
                last_attempt.get("status", 0), len(push_attempts), cid)
    _send_admin_notification(
        request_id, str(cid), claims, "email",
        current_email, new_email,
        {"emailVerified": True},
    )
    _send_customer_confirmation(claims, "email", new_email,
                                  {"emailVerified": True})

    return _json_response(200, {"ok": True, "status": "pending_review"})


def update_email(event: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy single-shot email change — kept for backward compat
    in case any old client still hits it. Customers from the portal
    now go through the two-step verify flow above."""
    return _json_response(410, {
        "error": "use_email_verify_flow",
        "detail": "POST /api/my-profile/email/start-verify then /confirm",
    })

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

    # Telnyx Verify — generic OTP-by-SMS, no phone-on-record
    # dependency. Same provider already powers login MFA. Vergent's
    # SBT path is gated on tenant-side provisioning we don't have.
    last4 = phone[-4:] if len(phone) >= 4 else phone
    ok, detail = telnyx_verify.start_sms(phone)
    log.info("phone verify-start ok=%s cid=%s last4=%s detail=%s",
             ok, cid, last4, detail)

    if not ok:
        return _json_response(502, {
            "error": "sms_send_failed",
            "detail": detail,
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

    # Verify the PIN via Telnyx (matches start-verify's provider).
    last4 = phone[-4:] if len(phone) >= 4 else phone
    approved, status_str = telnyx_verify.check(phone, code)
    log.info("phone verify-confirm approved=%s status=%s cid=%s last4=%s",
             approved, status_str, cid, last4)

    if not approved:
        return _json_response(400, {
            "error": "code_invalid_or_expired",
            "detail": status_str,
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


# ─────────────────────────────────────────
# Change password
# ─────────────────────────────────────────
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")


def _format_pacific_time(dt: datetime) -> str:
    """Format a naive UTC datetime for customer-facing display in
    Pacific time. Auto-handles PST/PDT via zoneinfo so the displayed
    label is always correct."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone as _tz
        local = dt.replace(tzinfo=_tz.utc).astimezone(ZoneInfo("America/Los_Angeles"))
        return local.strftime("%b %d, %Y at %I:%M %p %Z")
    except Exception:
        # Defensive fallback — Lambda Python 3.12 ships with tzdata,
        # so this branch shouldn't trigger in production. Approximates
        # PST (no DST awareness).
        from datetime import timedelta, timezone as _tz
        local = dt.replace(tzinfo=_tz.utc).astimezone(_tz(timedelta(hours=-8)))
        return local.strftime("%b %d, %Y at %I:%M %p PST")


def _validate_new_password(pw: str) -> Optional[str]:
    """Returns an error code if the password fails policy, else None.
    Mirror of typical Cognito default policy + sensible minimums."""
    if not pw or len(pw) < 12:
        return "too_short"
    if len(pw) > 128:
        return "too_long"
    if not any(c.isupper() for c in pw):
        return "needs_uppercase"
    if not any(c.islower() for c in pw):
        return "needs_lowercase"
    if not any(c.isdigit() for c in pw):
        return "needs_digit"
    return None


def _send_password_changed_alert(claims: Dict[str, Any]) -> None:
    """Email the customer that their password was just changed.
    Best-effort: failures log but don't propagate."""
    customer_email = (claims.get("email") or "").strip()
    if not customer_email:
        return
    first_name = (claims.get("given_name") or "").strip() or "there"
    when = _format_pacific_time(datetime.utcnow())

    text = (
        f"Hi {first_name},\n\n"
        f"Your Cash in Flash account password was just changed at {when}.\n\n"
        f"If this was you, no further action is needed.\n\n"
        f"If you did NOT change your password, your account may be at risk. "
        f"Please call us immediately at (747) 270-7121 and we'll secure your account.\n\n"
        f"---\n"
        f"Cash in Flash · Licensed by the California Department of "
        f"Financial Protection and Innovation #214840\n"
        f"This is an automated security notification. Please do not reply.\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,'SF Pro Text','Segoe UI',Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:36px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:36px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Security alert</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">Your password was changed</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">Hi {first_name}, this is a confirmation that your Cash in Flash account password was changed on <strong>{when}</strong>.</p>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">If this was you, no further action is needed.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#fef3f2;border-radius:10px;border-left:4px solid #dc2626;">
            <tr><td style="padding:14px 18px;color:#991b1b;font-size:14px;line-height:1.55;">
              <strong>Didn't change your password?</strong> Your account may be at risk.
              Call us right away at <a href="tel:+17472707121" style="color:#991b1b;font-weight:700;text-decoration:underline;">(747) 270-7121</a> and we'll secure it.
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:22px 36px 32px;border-top:1px solid #e5e7eb;background:#fafafa;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 6px;">Cash in Flash &middot; Licensed by the California Department of Financial Protection and Innovation #214840</p>
          <p style="margin:0;">This email was sent by Cash in Flash &middot; 13937B Van Nuys Blvd, Arleta, CA 91331. Please do not reply to this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    ok, err_code, err_msg = resend_email.send(
        to=customer_email,
        subject="Your Cash in Flash password was changed",
        text=text,
        html=html,
    )
    if not ok:
        log.warning("password-changed alert send failed code=%s msg=%s",
                    err_code, (err_msg or "")[:200])


def change_password(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-profile/password — change the customer's portal
    password. Verifies the current password by re-authenticating
    against Cognito, then sets the new password admin-side, then
    fires a security-alert email so the customer sees the change
    even if it wasn't them."""
    claims = _claims(event)
    if not claims.get("sub") or not claims.get("email"):
        return _json_response(401, {"error": "no_claims"})

    if not COGNITO_USER_POOL_ID or not COGNITO_APP_CLIENT_ID:
        log.warning("change_password called but Cognito env not configured")
        return _json_response(503, {"error": "not_configured"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    current_pw = body.get("currentPassword") or ""
    new_pw = body.get("newPassword") or ""
    if not current_pw or not new_pw:
        return _json_response(400, {"error": "missing_fields"})
    if current_pw == new_pw:
        return _json_response(400, {"error": "same_password"})
    pw_err = _validate_new_password(new_pw)
    if pw_err:
        return _json_response(400, {"error": pw_err})

    email = (claims.get("email") or "").strip()
    sub = claims.get("sub") or claims.get("cognito:username")

    # Step 1: verify the current password by re-authenticating.
    try:
        _cognito.admin_initiate_auth(
            UserPoolId=COGNITO_USER_POOL_ID,
            ClientId=COGNITO_APP_CLIENT_ID,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": current_pw},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        log.info("change_password reauth failed sub=%s code=%s", sub, code)
        # Use 400 (not 401) so the frontend's generic apiFetch
        # auto-logout-on-401 handler doesn't trigger. This is a
        # validation failure of the request body, not a session
        # auth failure — the customer's JWT is still valid.
        if code in ("NotAuthorizedException", "UserNotFoundException"):
            return _json_response(400, {"error": "current_password_incorrect"})
        if code == "PasswordResetRequiredException":
            return _json_response(400, {"error": "reset_required"})
        if code == "TooManyRequestsException":
            return _json_response(429, {"error": "rate_limited"})
        return _json_response(502, {"error": "auth_check_failed"})

    # Step 2: set the new password as permanent.
    try:
        _cognito.admin_set_user_password(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=sub,
            Password=new_pw,
            Permanent=True,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        log.warning("admin_set_user_password failed sub=%s code=%s", sub, code)
        if code == "InvalidPasswordException":
            return _json_response(400, {"error": "policy_violation"})
        return _json_response(502, {"error": "password_set_failed"})

    # Step 3: best-effort security-alert email.
    _send_password_changed_alert(claims)

    log.info("password changed sub=%s", sub)
    return _json_response(200, {"ok": True})


def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None, "reason": "no-customer-id"})

    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(200, {"loan": None, "loanCount": 0, "allLoans": []})

    # Patch any missing fees by summing payment transactions. Hits one
    # extra Vergent call per paid-off loan with fees=null; safe.
    _patch_missing_fees(cid, shaped)

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


def _extract_doc_rows(status: int, body: Any) -> List[Dict[str, Any]]:
    """Pull document records out of a Vergent v1 docs response,
    handling the various wrapper shapes Vergent can return."""
    if status != 200:
        return []
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in ("Items", "Documents", "Docs", "items", "documents", "docs"):
            v = body.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _fetch_payment_receipt_docs(cid: str, loan_id: Any,
                                 include_data: bool,
                                 seen: set) -> List[Dict[str, Any]]:
    """For each Payment-type transaction on this loan, fetch its
    attached receipt document via
    /V1/customer/{cid}/docs/loan/{loan_id}/trans/{tx_id}.

    Walks GetCustomerLoanHistory once, then makes one extra docs
    call per Payment transaction. Typical payday loan has 1-3
    payments so this stays small.
    """
    if loan_id in (None, ""):
        return []
    if _v1_user_id is None:
        _get_v1_token()
    uid = _v1_user_id or 0
    params = urllib.parse.urlencode({
        "custId": cid,
        "HdrId": loan_id,
        "companyId": VERGENT_COMPANY_ID,
        "storeId": 0,
        "userId": uid,
    })
    status, body = _v1_get(f"/V1/GetCustomerLoanHistory?{params}")
    if status != 200:
        log.info("loan-receipts history-status=%s loan=%s", status, loan_id)
        return []

    tx_rows: List[Dict[str, Any]] = []
    if isinstance(body, list):
        tx_rows = [r for r in body if isinstance(r, dict)]
    elif isinstance(body, dict):
        for key in ("Items", "Transactions", "History", "LoanHistory"):
            v = body.get(key)
            if isinstance(v, list):
                tx_rows = [r for r in v if isinstance(r, dict)]
                break

    out: List[Dict[str, Any]] = []
    for tx in tx_rows:
        if tx.get("IsVoid"):
            continue
        # Vergent labels: "Payment", "ACH Payment", "Card Payment",
        # etc. Filter to transactions whose Type/Label says payment.
        tx_type = str(tx.get("Type") or tx.get("Label") or "").lower()
        if "payment" not in tx_type:
            continue
        tx_id = tx.get("Id")
        if not tx_id:
            continue

        tx_path = f"/V1/customer/{cid}/docs/loan/{loan_id}/trans/{tx_id}"
        tx_status, tx_body = _v1_get(tx_path)
        receipt_rows = _extract_doc_rows(tx_status, tx_body)
        log.info("loan-receipts loan=%s tx=%s status=%s rows=%d",
                 loan_id, tx_id, tx_status, len(receipt_rows))

        for r in receipt_rows:
            shaped = _shape_v1_document(r, loan_id, "transaction",
                                         include_data=include_data)
            if not shaped or shaped["id"] in seen:
                continue
            # Override displayName so receipts read clearly even if
            # Vergent's DocumentName is generic.
            existing_name = (shaped.get("displayName") or "").lower()
            if "receipt" not in existing_name:
                date_str = shaped.get("documentDate") or tx.get("BusDate") or ""
                shaped["displayName"] = (
                    "Payment receipt" + (" · " + date_str if date_str else "")
                )
            seen.add(shaped["id"])
            out.append(shaped)
    return out


def _list_v1_loan_docs(cid: str, loan_id: Any,
                       include_data: bool = False) -> List[Dict[str, Any]]:
    """List signed documents attached to a specific loan via Vergent v1.

    Two sources:
      1. Origination docs (Advance Contract, DDT Disclosure,
         Advance Receipt) via /V1/customer/{cid}/docs/loan/{hdr}.
      2. Per-payment receipts via
         /V1/customer/{cid}/docs/loan/{hdr}/trans/{txId} for each
         Payment-type transaction on the loan.

    Each returned record is filtered to ensure its `HdrId` matches
    the requested `loan_id` — a defensive safeguard against Vergent
    occasionally returning cross-loan docs (observed empirically
    with the user's account).

    With include_data=True, each shaped doc carries its raw Data +
    DocumentUrl for the download path to use.
    """
    if loan_id in (None, ""):
        return []

    out: List[Dict[str, Any]] = []
    seen: set = set()

    # 1. Origination docs
    path = f"/V1/customer/{cid}/docs/loan/{loan_id}"
    status, body = _v1_get(path)
    rows = _extract_doc_rows(status, body)
    log.info("loan-docs origination loan=%s status=%s rows=%d names=%s",
             loan_id, status, len(rows),
             [str(r.get("DocumentName") or "")[:40] for r in rows[:6]])

    for r in rows:
        # Defensive filter: drop records whose own HdrId doesn't
        # match the requested loan. Protects against Vergent
        # returning the wrong loan's documents.
        record_hdr = r.get("HdrId") or r.get("hdr_id")
        if record_hdr not in (None, "") and str(record_hdr) != str(loan_id):
            log.warning("loan-docs hdr_mismatch requested=%s record=%s name=%s",
                        loan_id, record_hdr, r.get("DocumentName"))
            continue
        shaped = _shape_v1_document(r, loan_id, "loan", include_data=include_data)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)

    # 2. Per-payment receipts (one extra fetch per Payment tx)
    try:
        receipts = _fetch_payment_receipt_docs(cid, loan_id,
                                                include_data=include_data,
                                                seen=seen)
        out.extend(receipts)
    except Exception as e:
        log.warning("loan-receipts unexpected loan=%s err=%s",
                    loan_id, type(e).__name__)

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
        if path.endswith("/my-profile/email/start-verify") and method == "POST":
            return start_email_verify(event)
        if path.endswith("/my-profile/email/confirm") and method == "POST":
            return confirm_email_verify(event)
        if path.endswith("/my-profile/address") and method == "PUT":
            return update_address(event)
        if path.endswith("/my-profile/phone/start-verify") and method == "POST":
            return start_phone_verify(event)
        if path.endswith("/my-profile/phone/confirm") and method == "POST":
            return confirm_phone_verify(event)
        if path.endswith("/my-profile/password") and method == "POST":
            return change_password(event)
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
