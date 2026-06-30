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
  GET  /api/my-esign/pending                  -> pending e-sign requests for this customer
  POST /api/my-esign/resend                   -> re-trigger e-sign email for {"loanId": N}
  GET  /api/my-esign/document?loanId=N        -> fetch unsigned doc set for in-portal signing
  POST /api/my-esign/sign                     -> submit signature {"loanId", "signerName", "agreed"}
  POST /api/plaid/link-token                  -> mint a Plaid Link token
  POST /api/plaid/exchange                    -> public_token → access_token + persist
  GET  /api/plaid/connections                 -> list this customer's linked banks
  DELETE /api/plaid/connections/{itemId}      -> revoke a connection
  GET  /api/admin/plaid/customers             -> [admin] every customer with a portal Plaid link
  GET  /api/admin/plaid/customer/{cid}        -> [admin] full detail incl. Plaid /accounts/get
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
import re
import secrets as _secrets_module  # avoid clash with `_secrets` boto client
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
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

# Plaid bank-link — used by the Profile page "Connect your bank"
# flow + the dashboard CTA card. See handlers/plaid.py.
from handlers import plaid
# auth_mfa is imported lazily inside the customer-search helpers
# (search_admin_customers / _search_portal_customers). Its module
# body reads os.environ["COGNITO_USER_POOL_ID"] with square brackets
# — required-by-shape — and many Lambdas that import loans.py
# (payments, etc.) don't carry that env var. Top-level importing
# auth_mfa here KeyError'd those Lambdas on cold start, returning
# the API Gateway default 500 to every customer call.

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
# Tolerate missing VERGENT_SECRET_ARN at import time — the loans
# Lambda will always have it set, but other Lambdas that import
# this module (payments, etc.) may not yet have caught up to a
# provisioning change. A missing env var produces a clear runtime
# error at the call site (_get_v1_token), not an opaque 500 from
# API-Gateway's default body on a failed Lambda construction.
VERGENT_SECRET_ARN = os.environ.get("VERGENT_SECRET_ARN", "")
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
PORTAL_PUBLIC_URL = os.environ.get("PORTAL_PUBLIC_URL", "https://my.cashinflash.com")
# Fast Re-Apply — the additive cif-apply intake endpoint. The portal
# resolves the logged-in customer's identity + linked bank SERVER-SIDE and
# hands cif-apply a re-loan, which runs the SAME engine + dashboard
# pipeline a normal application uses (tagged source="portal_reloan" / "RL").
# REAPPLY_SHARED_SECRET is optional and must match cif-apply's
# PORTAL_REAPPLY_SECRET when set; left blank, the endpoint still works.
CIF_APPLY_REAPPLY_URL = os.environ.get(
    "CIF_APPLY_REAPPLY_URL", "https://cif-apply.onrender.com/api/portal-reapply"
)
REAPPLY_SHARED_SECRET = os.environ.get("REAPPLY_SHARED_SECRET", "")
REAPPLY_MIN_AMOUNT = 100
REAPPLY_MAX_AMOUNT = 255
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

# Remembered index of the _fetch_all_loans candidate endpoint that last
# returned data. We try the known-good shape FIRST so we don't re-pay the
# fallback chain's wasted round-trips on every request. The working endpoint
# shape is a Vergent API capability (same for every customer), so one
# module-level hint is correct and self-healing across warm invocations.
_fetch_loans_winner_idx: int = 0

# Front-end origin allowed to call our API. Locked down from "*" so a
# malicious site can't relay a logged-in customer's browser into our
# API. Override via env var when adding a custom domain. Browsers will
# still block any cross-origin request that doesn't echo this back.
ALLOWED_ORIGIN = os.environ.get(
    "PORTAL_ORIGIN", "https://my.cashinflash.com"
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
    """JWT claims for the request — or, if X-Impersonation-Token is
    present, synthesized claims for the target customer. See
    handlers/impersonation.py for the override logic. Each call
    is cached on the event dict so we only hit DDB once per
    invocation."""
    from handlers import impersonation
    return impersonation.claims_with_impersonation(event)


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
            else _normalize_closed_status(hdr.get("SubStatus"), status_id)
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
        # Heuristic kept for back-compat (next payment < full payoff). NOT
        # reliable for fresh loans where amountDue can be < payoff without a
        # plan — use `hasPaymentPlan` (Vergent's authoritative RPP flag) to
        # decide whether a repayment plan is actually active.
        "onPaymentPlan": (
            amount_due is not None and payoff is not None
            and amount_due + 0.01 < payoff
        ),
        # Authoritative "an active repayment plan exists" flag from Vergent.
        "hasPaymentPlan": (str(hdr.get("RPP", "")).strip().upper() == "Y"),
        "nextDueDate": _format_iso(hdr.get("DueDate") or hdr.get("NextPaymentDate")),
        "nextDueAmount": next_due,
        "originationDate": _format_iso(hdr.get("OriginationDate")),
        "loanDate": _format_iso(hdr.get("LoanDate")),
        "fundingDate": _format_iso(hdr.get("FundingDate")),
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


# Vergent v1 statusId values that mark loans the customer should
# never see — the 2 known examples are ghost application records
# the underwriting flow leaves behind:
#   statusId 10 -> Deleted     (ghost application records)
# Add new bad statusIds here as we encounter them.
_HIDDEN_STATUS_IDS = {10}

# Substrings (case-insensitive) in any status text field that mean
# "this loan is not real or shouldn't be displayed". Drives the
# denylist branch of _is_visible_loan.
_HIDDEN_STATUS_TOKENS = ("delet", "cancel", "void")


def _normalize_closed_status(sub_status: Optional[str], status_id: Any) -> str:
    """Pick the customer-facing label for a non-outstanding loan.

    "Bought Back" loans are functionally paid off (Vergent rolls them
    into a fresh advance); we relabel them so the customer sees a
    consistent "Paid Off" pill across both flows. Anything else falls
    back to Vergent's SubStatus text, then to "Paid Off" as the
    default for non-outstanding records (we already filtered out
    Deleted/Cancelled in _is_visible_loan, so anything that lands
    here is a settled loan in good standing).
    """
    if sub_status:
        text = str(sub_status).strip().lower()
        if "bought" in text or "paid" in text:
            return "Paid Off"
        return str(sub_status)
    return "Paid Off"


def _is_visible_loan(loan: Dict[str, Any]) -> bool:
    """Filter Vergent's raw loan list down to what a customer should see.

    Denylist approach: show everything that has real loan substance
    (principal > 0) except records explicitly tagged as Deleted /
    Cancelled / Voided. The previous allowlist ("must contain
    'paid'") was hiding settled-but-relabeled loans like Bought Back.
    """
    if loan.get("isOutstanding"):
        return True

    sid = loan.get("statusId")
    try:
        if int(sid) in _HIDDEN_STATUS_IDS:
            return False
    except (TypeError, ValueError):
        pass

    candidates = (loan.get("status"), loan.get("subStatus"), loan.get("rawStatus"))
    for raw in candidates:
        if not raw:
            continue
        text = str(raw).strip().lower()
        if any(tok in text for tok in _HIDDEN_STATUS_TOKENS):
            return False

    # Ghost records have principal=0 and NULL status fields — drop
    # them so the history doesn't list empty entries.
    principal = loan.get("principal")
    try:
        if not principal or float(principal) <= 0:
            return False
    except (TypeError, ValueError):
        return False

    return True


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
    # Try the last-known-good endpoint first (self-healing), then the rest in
    # order. Saves 1-2 wasted Vergent round-trips per request when the broadest
    # candidate isn't the one this Vergent tenant actually serves.
    global _fetch_loans_winner_idx
    order = list(range(len(candidates)))
    if 0 <= _fetch_loans_winner_idx < len(candidates):
        order.remove(_fetch_loans_winner_idx)
        order.insert(0, _fetch_loans_winner_idx)
    for i in order:
        status, body = _v1_get(candidates[i])
        if status == 200 and isinstance(body, list):
            _fetch_loans_winner_idx = i
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
    call; those calls are fired CONCURRENTLY (see below) so total wall
    time is ~one call regardless of how many paid-off loans a customer
    has.
    """
    # Collect the loans that actually need a history call.
    targets = []
    for loan in loans:
        if loan.get("fees") is not None:
            continue
        principal = _to_number(loan.get("principal"))
        hdr_id = loan.get("id")
        if not principal or not hdr_id or principal <= 0:
            continue
        targets.append(loan)
    if not targets:
        return

    # Pre-warm the v1 token ONCE up front so the worker threads all reuse the
    # cached token + userId (module globals) rather than each racing to fetch a
    # fresh one. On a warm container this is already populated — a no-op.
    if _v1_token is None or _v1_user_id is None:
        _get_v1_token()
    uid = _v1_user_id or 0

    def _patch_one(loan: Dict[str, Any]) -> None:
        principal = _to_number(loan.get("principal"))
        hdr_id = loan.get("id")
        store_id = loan.get("storeId")
        # Direct raw v1 call — Vergent's transactions store the fee
        # under a `Fee` column distinct from `Amount`, and the running
        # balance is in `Balance`. Peak balance = principal + total
        # fees, so we derive fees from that. Works for any loan type
        # without needing to know which "Type" string is the fee row.
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
            return
        if status != 200:
            return
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
            return

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

    # Fire the per-loan history calls CONCURRENTLY — each is independent, each
    # mutates a different loan dict, and _http is stateless (one urllib request
    # per call), so this is thread-safe. Collapses N sequential ~1s Vergent
    # round-trips into ~1. Every worker is fully self-guarded (a failure just
    # leaves that loan's fees=null → UI shows "—", exactly as before), and we
    # fall back to sequential if the pool can't start.
    if len(targets) == 1:
        _patch_one(targets[0])
        return
    try:
        # ThreadPoolExecutor is imported at module top.
        with ThreadPoolExecutor(max_workers=min(len(targets), 6)) as ex:
            list(ex.map(_patch_one, targets))
    except Exception as e:
        log.warning("patch-fees parallel failed (%s); running sequentially",
                    type(e).__name__)
        for loan in targets:
            _patch_one(loan)


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
          "(888) 999-9859.\n\n"
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
          <img src="https://my.cashinflash.com/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Account update received</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">We've got your request, {first_name}.</h1>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#1a1a2e;">We've received your request to update the <strong>{field_label}</strong> on your Cash in Flash account.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#f9fafb;border-radius:10px;">
            {requested_row}
          </table>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#1a1a2e;">For your security, this change is reviewed by a Cash in Flash specialist before it takes effect — usually within <strong>one business day</strong>. We'll email you once it's applied.</p>
          <p style="margin:0 0 4px;font-size:13px;line-height:1.6;color:#6b7280;">Didn't request this? Call us right away at <a href="tel:+18889999859" style="color:#0E8741;font-weight:600;text-decoration:none;">(888) 999-9859</a>.</p>
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
        f"or call us at (888) 999-9859.\n\n"
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
          <img src="https://my.cashinflash.com/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:32px 36px 8px;">
          <p style="margin:0 0 8px;font-size:13px;color:#6b7280;letter-spacing:.06em;text-transform:uppercase;font-weight:600;">Verification code</p>
          <h1 style="margin:0 0 18px;font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;">{code}</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:#1a1a2e;">Enter this code in your account profile to confirm <strong>{to_email}</strong>.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#6b7280;">This code expires in <strong>10 minutes</strong>. If you didn't request this change, you can safely ignore this email or call us at <a href="tel:+18889999859" style="color:#0E8741;text-decoration:none;font-weight:600;">(888) 999-9859</a>.</p>
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
        f"(888) 999-9859 so we can secure your account.\n\n"
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
          <img src="https://my.cashinflash.com/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Email updated</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">Your email address is now active.</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">Hi {first_name}, your Cash in Flash account email is now <strong>{new_email}</strong>, effective {when}.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#1a1a2e;">Future account notices, sign-in codes, and statements will be delivered here. There's nothing else you need to do.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#fef3f2;border-radius:10px;border-left:4px solid #dc2626;">
            <tr><td style="padding:14px 18px;color:#991b1b;font-size:14px;line-height:1.55;">
              <strong>Didn't make this change?</strong> Call us right away at <a href="tel:+18889999859" style="color:#991b1b;font-weight:700;text-decoration:underline;">(888) 999-9859</a> and we'll secure your account.
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
        f"Please call us immediately at (888) 999-9859 and we'll secure your account.\n\n"
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
          <img src="https://my.cashinflash.com/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 36px 8px;">
          <p style="margin:0 0 6px;font-size:12px;color:#0E8741;letter-spacing:.08em;text-transform:uppercase;font-weight:700;">Security alert</p>
          <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.01em;line-height:1.25;">Your password was changed</h1>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">Hi {first_name}, this is a confirmation that your Cash in Flash account password was changed on <strong>{when}</strong>.</p>
          <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#1a1a2e;">If this was you, no further action is needed.</p>
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:6px 0 22px;background:#fef3f2;border-radius:10px;border-left:4px solid #dc2626;">
            <tr><td style="padding:14px 18px;color:#991b1b;font-size:14px;line-height:1.55;">
              <strong>Didn't change your password?</strong> Your account may be at risk.
              Call us right away at <a href="tel:+18889999859" style="color:#991b1b;font-weight:700;text-decoration:underline;">(888) 999-9859</a> and we'll secure it.
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


def _attach_pending_signature(cid: str, loan: Optional[Dict[str, Any]]) -> None:
    """An outstanding loan that hasn't funded yet may be waiting on the
    customer's e-signature. The v1 loan record can't tell us that on its own
    (the signing flags live on the CustomerPortal API our service token can't
    reach), so cross-reference the e-sign pending queue — it's authoritative
    and carries the hosted `signingUrl`. On a match we flag the loan so the
    portal shows a "sign your agreement" state (and blocks payment) instead of
    a normal active-loan card; the moment Vergent drops it from the queue
    (i.e. the customer signed) the flag clears and the loan reads as active —
    no waiting on the slower Pending->Held customer-status change.

    Mutates `loan` in place. Best-effort: any failure leaves it as active.
    Gated on fundingDate being empty so funded loans skip the extra call.
    """
    if not loan:
        return
    if loan.get("fundingDate"):
        loan["lifecycle"] = "active"
        return
    try:
        pending = _fetch_pending_esign(cid)
    except Exception:
        pending = []
    lid = str(loan.get("id"))
    pid = loan.get("publicId")
    match = next(
        (p for p in pending
         if str(p.get("loanId")) == lid
         or (p.get("publicLoanId") and pid and str(p.get("publicLoanId")) == str(pid))),
        None,
    )
    if match:
        loan["pendingSignature"] = True
        loan["lifecycle"] = "pending_signature"
        loan["esign"] = {
            "id": match.get("id"),
            "signingUrl": match.get("signingUrl"),
            "documentName": match.get("documentName"),
        }
    else:
        loan["lifecycle"] = "active"


# ─────────────────────────────────────────
# Plan-installment memory (DynamoDB)
# ─────────────────────────────────────────
# Vergent stops reporting the next installment's amount once the current one is
# paid (it returns $0 due + the remaining payoff until the next due date). So we
# remember the installment the first time we see it and surface it as
# `planInstallment` between due dates. Best-effort: ANY failure just leaves the
# field unset and the UI falls back to the balance + pay-off (pre-persistence
# behaviour) — never raises.
_PLAN_TABLE = os.environ.get("PLAN_INSTALLMENTS_TABLE", "cif-portal-plan-installments-dev")
_ddb_plan = None


def _plan_ddb():
    global _ddb_plan
    if _ddb_plan is None:
        _ddb_plan = boto3.client(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _ddb_plan


# ── Presence (admin "online" dot) ─────────────────────────────────────────
# Lightweight heartbeat: the portal frontend pings /api/presence/ping every
# ~45s while the customer's tab is visible, stamping lastSeenAt here. The admin
# customers page reads it to show an online/offline dot. Fully additive +
# best-effort: a failure anywhere just means "no dot", never a broken flow.
_PRESENCE_TABLE = os.environ.get("PRESENCE_TABLE", "cif-portal-presence-dev")
_PRESENCE_ONLINE_MS = 90 * 1000        # "online" = pinged within the last 90s
_ddb_presence = None


def _presence_ddb():
    global _ddb_presence
    if _ddb_presence is None:
        _ddb_presence = boto3.client(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _ddb_presence


def record_presence(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/presence/ping (Cognito-JWT authed). Stamp the caller's
    last-seen time. Best-effort; never raises into the customer's session."""
    claims = _claims(event)
    sub = claims.get("sub") or claims.get("cognito:username")
    if not sub:
        return _json_response(401, {"error": "no_claims"})
    item = {
        "sub": {"S": str(sub)},
        "lastSeenAt": {"N": str(int(time.time() * 1000))},
        # TTL well past the 90s online window so rows GC on their own.
        "expiresAt": {"N": str(int(time.time()) + 900)},
    }
    cid = _customer_id(claims)
    if cid:
        item["customerId"] = {"S": str(cid)}
    try:
        _presence_ddb().put_item(TableName=_PRESENCE_TABLE, Item=item)
    except Exception as e:
        log.info("presence ping skipped sub=%s err=%s", sub, type(e).__name__)
    return _json_response(200, {"ok": True})


def _annotate_presence(rows: List[Dict[str, Any]]) -> None:
    """Add `online` (bool) + `lastSeenMs` to each portal-source row from the
    presence table. Batched read; best-effort (rows default to offline)."""
    for r in rows:
        if r.get("source") == "portal":
            r.setdefault("online", False)
    subs = [r.get("cognitoSub") for r in rows
            if r.get("source") == "portal" and r.get("cognitoSub")]
    if not subs:
        return
    now_ms = int(time.time() * 1000)
    seen: Dict[str, int] = {}
    try:
        for i in range(0, len(subs), 100):     # batch_get_item caps at 100 keys
            chunk = subs[i:i + 100]
            resp = _presence_ddb().batch_get_item(RequestItems={
                _PRESENCE_TABLE: {"Keys": [{"sub": {"S": str(s)}} for s in chunk]}
            })
            for it in resp.get("Responses", {}).get(_PRESENCE_TABLE, []):
                s = (it.get("sub") or {}).get("S")
                ls = (it.get("lastSeenAt") or {}).get("N")
                if s and ls:
                    seen[s] = int(ls)
    except Exception as e:
        log.info("presence read skipped err=%s", type(e).__name__)
        return
    for r in rows:
        ls = seen.get(r.get("cognitoSub"))
        if ls:
            r["lastSeenMs"] = ls
            r["online"] = (now_ms - ls) <= _PRESENCE_ONLINE_MS


def _remember_plan_installment(loan_id: Any, amount: Optional[float]) -> None:
    if not loan_id or amount is None:
        return
    try:
        exp = int(time.time()) + 120 * 24 * 3600  # 120-day TTL (DynamoDB GC)
        _plan_ddb().put_item(TableName=_PLAN_TABLE, Item={
            "loanId": {"S": str(loan_id)},
            "installment": {"N": str(round(float(amount), 2))},
            "expiresAt": {"N": str(exp)},
        })
    except Exception as e:
        log.info("plan-installment remember skipped loan=%s err=%s", loan_id, type(e).__name__)


def _recall_plan_installment(loan_id: Any) -> Optional[float]:
    if not loan_id:
        return None
    try:
        r = _plan_ddb().get_item(TableName=_PLAN_TABLE, Key={"loanId": {"S": str(loan_id)}})
        item = r.get("Item")
        if item and "installment" in item:
            return float(item["installment"]["N"])
    except Exception as e:
        log.info("plan-installment recall skipped loan=%s err=%s", loan_id, type(e).__name__)
    return None


def _apply_plan_installment(loan: Optional[Dict[str, Any]]) -> None:
    """Set loan['planInstallment'] so the next plan payment shows even after the
    current installment is paid. Only for loans with an active plan (RPP=Y).
    Best-effort; mutates in place."""
    if not loan or not loan.get("hasPaymentPlan"):
        return
    loan_id = loan.get("id")
    payoff = _to_number(loan.get("payoffAmount"))
    if payoff is None:
        payoff = _to_number(loan.get("balance"))
    amount_due = _to_number(loan.get("amountDue"))
    # A real installment is due now → that IS the installment; remember it.
    if (amount_due is not None and amount_due > 0.005
            and payoff is not None and amount_due + 0.01 < payoff):
        loan["planInstallment"] = round(amount_due, 2)
        _remember_plan_installment(loan_id, amount_due)
        return
    # Caught up (nothing due right now) but the plan's still active → recall the
    # stored installment, capped at the remaining balance (handles the final,
    # smaller payment).
    recalled = _recall_plan_installment(loan_id)
    if recalled is not None and recalled > 0.005:
        if payoff is not None and recalled > payoff:
            recalled = payoff
        loan["planInstallment"] = round(recalled, 2)


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
    # Flag the active loan if it's still awaiting the customer's e-signature
    # (so the dashboard/loans pages can show a "sign" state, not a healthy card).
    _attach_pending_signature(cid, active)
    # Remember/recall the plan installment so the next payment shows after the
    # current one is paid (Vergent hides it between due dates).
    _apply_plan_installment(active)
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
        record.get("Id") or record.get("id")
        or record.get("DocId") or record.get("docId")
        or record.get("DocumentId") or record.get("documentId")
        or record.get("ChainId")  # last-resort fallback only
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
    # Drop E-Sign Receipt records — Vergent's internal audit
    # artifact for the signing ceremony, never something a customer
    # should see in the portal. Match the full phrase so the loan
    # agreement ("Advance Contract w E-Sign") stays visible.
    hay = " ".join((str(fname), str(title),
                    str(record.get("DocTypeName") or ""))).lower()
    if ("e-sign receipt" in hay
            or "esign receipt" in hay
            or "esign_receipt" in hay
            or "electronic signature receipt" in hay):
        return None
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


def _history_params(cid: str, loan_id: Any) -> str:
    """Build the GetCustomerLoanHistory query string. Token must
    already be loaded so _v1_user_id is set."""
    uid = _v1_user_id or 0
    return urllib.parse.urlencode({
        "custId": cid,
        "HdrId": loan_id,
        "companyId": VERGENT_COMPANY_ID,
        "storeId": 0,
        "userId": uid,
    })


def _extract_history_rows(status: int, body: Any) -> List[Dict[str, Any]]:
    """Pull tx records out of a Vergent GetCustomerLoanHistory
    response, accepting both bare-list and wrapped shapes."""
    if status != 200:
        return []
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in ("Items", "Transactions", "History", "LoanHistory"):
            v = body.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _shape_payment_receipts(loan_id: Any,
                            include_data: bool,
                            seen: set,
                            tx_results: List[Tuple[Dict[str, Any], Tuple[int, Any]]]
                            ) -> List[Dict[str, Any]]:
    """Convert raw per-tx Vergent doc responses into shaped receipt
    docs. Pure transformation — no I/O. Caller already fanned out
    the HTTP requests in parallel and collected the responses."""
    out: List[Dict[str, Any]] = []
    for tx, (tx_status, tx_body) in tx_results:
        receipt_rows = _extract_doc_rows(tx_status, tx_body)
        if not receipt_rows:
            continue
        tx_id = tx.get("Id")
        tx_type = str(tx.get("Type")
                      or tx.get("TransactionType")
                      or tx.get("Description") or "")
        log.info("loan-receipts loan=%s tx=%s type=%s status=%s rows=%d",
                 loan_id, tx_id, tx_type, tx_status, len(receipt_rows))
        for r in receipt_rows:
            shaped = _shape_v1_document(r, loan_id, "transaction",
                                         include_data=include_data)
            if not shaped:
                continue
            base_id = shaped["id"]
            # Vergent's per-tx docs endpoint sometimes returns the
            # loan's origination docs back-of-house alongside (or
            # instead of) the actual receipt for that tx. Those
            # reappear here with the same Id we already shaped from
            # the origination / OtherFiles passes — skip them so
            # they don't get re-labelled as "Payment receipt".
            if base_id in seen:
                continue
            # Disambiguate by tx so two distinct receipts that
            # happen to share a Vergent doc id (ChainId-style
            # collisions, observed empirically) still both survive.
            # Don't seed the base_id into seen here — that would
            # block the next tx's receipt if Vergent reuses the
            # same Id across them.
            shaped["id"] = "{}:tx:{}".format(base_id, tx_id)
            if shaped["id"] in seen:
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


def _filter_doc_row(r: Dict[str, Any], loan_id: Any,
                    cutoff: Optional[datetime],
                    bucket_label: str) -> bool:
    """Apply the cross-loan safeguards to one Vergent doc row.
    Returns True when the row should be kept, False when it should
    be dropped. Logs the reason on each drop so we can see leaks
    in CloudWatch."""
    record_hdr = r.get("HdrId") or r.get("hdr_id")
    if record_hdr not in (None, "") and str(record_hdr) != str(loan_id):
        log.warning("loan-docs %s hdr_mismatch requested=%s record=%s name=%s",
                    bucket_label, loan_id, record_hdr, r.get("DocumentName"))
        return False
    if cutoff is not None:
        doc_date_raw = (
            r.get("DocumentDate") or r.get("documentDate")
            or r.get("Date") or r.get("date")
            or r.get("CreatedDate") or r.get("createdDate")
        )
        if doc_date_raw:
            try:
                doc_dt = datetime.fromisoformat(str(doc_date_raw)[:10])
                if doc_dt < cutoff:
                    log.warning("loan-docs %s date_too_old loan=%s name=%s "
                                "doc_date=%s",
                                bucket_label, loan_id,
                                r.get("DocumentName"), doc_date_raw)
                    return False
            except (ValueError, TypeError):
                pass  # un-parseable → keep, defensive
    return True


def _list_v1_loan_docs(cid: str, loan_id: Any,
                       include_data: bool = False,
                       loan_origin_iso: Optional[str] = None
                       ) -> List[Dict[str, Any]]:
    """List signed documents attached to a specific loan via Vergent v1.

    Three sources, all fetched in parallel via a ThreadPoolExecutor:
      1. Origination docs (Advance Contract, DDT Disclosure,
         Advance Receipt) via /V1/customer/{cid}/docs/loan/{hdr}.
      2. Auto-generated extras (payoff receipt, etc.) via
         /V1/customer/{cid}/docs/loan/{hdr}/OtherFiles.
      3. Per-payment receipts via
         /V1/customer/{cid}/docs/loan/{hdr}/trans/{txId} for each
         non-void transaction on the loan. Discovered by issuing
         GetCustomerLoanHistory in parallel with #1 and #2, then
         fanning out one fetch per tx as soon as the history
         response arrives.

    Two cross-loan safeguards on origination + OtherFiles rows:
      - Drop records whose own HdrId disagrees with the requested
        loan id.
      - Drop records dated >7 days before the requested loan's own
        origination date (Vergent's /docs/loan/{hdr} endpoint
        returns rows for the entire chain on active loans, and
        HdrId on those leaked rows is sometimes the chain id
        rather than a previous-loan id — date is the more reliable
        signal).

    Receipts are fetched per-tx using ids from this loan's own
    history, so they don't need date filtering.

    With include_data=True, each shaped doc carries its raw Data +
    DocumentUrl for the download path to use.
    """
    if loan_id in (None, ""):
        return []

    # Pre-fetch the service token before fanning out: _get_v1_token
    # mutates module-level globals (token, exp, user_id) and isn't
    # locked. Doing the fetch synchronously here keeps the parallel
    # workers on a settled cache. On warm Lambda this is a no-op.
    if _v1_token is None or _v1_user_id is None:
        _get_v1_token()

    cutoff: Optional[datetime] = None
    if loan_origin_iso:
        try:
            cutoff = datetime.fromisoformat(str(loan_origin_iso)[:10]) - timedelta(days=7)
        except (ValueError, TypeError):
            cutoff = None

    orig_path = f"/V1/customer/{cid}/docs/loan/{loan_id}"
    other_path = f"/V1/customer/{cid}/docs/loan/{loan_id}/OtherFiles"
    history_path = f"/V1/GetCustomerLoanHistory?{_history_params(cid, loan_id)}"

    with ThreadPoolExecutor(max_workers=12) as ex:
        # Tier 1: three independent listing calls fire in parallel.
        f_orig = ex.submit(_v1_get, orig_path)
        f_other = ex.submit(_v1_get, other_path)
        f_history = ex.submit(_v1_get, history_path)

        orig_status, orig_body = f_orig.result()
        other_status, other_body = f_other.result()
        hist_status, hist_body = f_history.result()

        # Tier 2: as soon as we have the tx list, fan out one
        # receipt fetch per non-void transaction.
        tx_rows = _extract_history_rows(hist_status, hist_body)
        tx_futures: List[Tuple[Dict[str, Any], Any]] = []
        for tx in tx_rows:
            if tx.get("IsVoid"):
                continue
            tx_id = tx.get("Id")
            if not tx_id:
                continue
            tx_path = f"/V1/customer/{cid}/docs/loan/{loan_id}/trans/{tx_id}"
            tx_futures.append((tx, ex.submit(_v1_get, tx_path)))

        tx_results = [(tx, fut.result()) for tx, fut in tx_futures]

    # All HTTP done; everything below is pure CPU.

    out: List[Dict[str, Any]] = []
    seen: set = set()

    # 1. Origination docs
    orig_rows = _extract_doc_rows(orig_status, orig_body)
    log.info("loan-docs origination loan=%s status=%s rows=%d names=%s",
             loan_id, orig_status, len(orig_rows),
             [str(r.get("DocumentName") or "")[:40] for r in orig_rows[:6]])
    for r in orig_rows:
        if not _filter_doc_row(r, loan_id, cutoff, "origination"):
            continue
        shaped = _shape_v1_document(r, loan_id, "loan", include_data=include_data)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)

    # 2. OtherFiles
    other_rows = _extract_doc_rows(other_status, other_body)
    if other_rows:
        log.info("loan-docs other-files loan=%s status=%s rows=%d names=%s",
                 loan_id, other_status, len(other_rows),
                 [str(r.get("DocumentName") or "")[:40] for r in other_rows[:6]])
    for r in other_rows:
        if not _filter_doc_row(r, loan_id, cutoff, "other-files"):
            continue
        shaped = _shape_v1_document(r, loan_id, "loan", include_data=include_data)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)

    # 3. Per-tx payment receipts (already fetched in parallel above)
    try:
        receipts = _shape_payment_receipts(loan_id, include_data, seen, tx_results)
        out.extend(receipts)
    except Exception as e:
        log.warning("loan-receipts unexpected loan=%s err=%s",
                    loan_id, type(e).__name__)

    if orig_status not in (200, 404):
        log.warning("v1 loan-docs %s status=%s loan=%s",
                    orig_path, orig_status, loan_id)

    # Newest first.
    out.sort(key=lambda item: str(item.get("documentDate") or ""), reverse=True)
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

    loan_id = loan.get("id")
    loan_origin_iso = loan.get("loanDate") or loan.get("originationDate")
    docs = _list_v1_loan_docs(cid, loan_id, loan_origin_iso=loan_origin_iso)
    return _json_response(200, {
        "documents": docs,
        "loanId": loan_id,
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
    hint_loan_id = (qs or {}).get("loanId") if isinstance(qs, dict) else None

    # Ownership check + content fetch: walk this customer's loans and
    # find the matching docId. Vergent's listing endpoint inlines the
    # document content as base64 in the `Data` field, so a single
    # listing call gets us both ownership confirmation AND the content
    # — no separate binary download endpoint needed.
    #
    # When the frontend passes ?loanId=N (it always does for docs
    # rendered from the loan-detail page), we scope the walk to that
    # one loan instead of every loan on file. Walking every loan
    # blows the Lambda budget on customers with 2-3 paid-off loans
    # because each loan triggers its own receipt-history walk.
    shaped = _fetch_all_loans(cid)
    if not shaped:
        return _json_response(404, {"error": "doc_not_found"})
    if hint_loan_id:
        loans_to_check = [
            l for l in shaped
            if str(l.get("id")) == str(hint_loan_id)
            or str(l.get("publicId") or "") == str(hint_loan_id)
        ]
        if not loans_to_check:
            # Hint pointed at a loan that isn't on this customer —
            # fall back to the full walk rather than return 404,
            # in case the hint is stale.
            loans_to_check = shaped
    else:
        loans_to_check = shaped
    matched = None
    for loan in loans_to_check:
        docs = _list_v1_loan_docs(
            cid, loan.get("id"), include_data=True,
            loan_origin_iso=loan.get("loanDate") or loan.get("originationDate"),
        )
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


# ─────────────────────────────────────────
# E-sign — pending signatures + resend link
# ─────────────────────────────────────────

def _extract_hdr_id_from_esign_doc(body: Any) -> Optional[Any]:
    """Pull the loan's HdrId out of a /esign/sign/{guid} response.

    Vergent's response shape isn't documented; this scans the most
    likely places (top-level field, nested Loan object, first item
    of any Documents/Items array). Returns None if nothing matches —
    caller logs the response shape so we can refine.
    """
    if not isinstance(body, dict):
        return None
    for key in ("HdrId", "hdr_id", "LoanHeaderId", "loanHeaderId",
                "LoanId", "loanId", "Hdr"):
        v = body.get(key)
        if v:
            return v
    loan = body.get("Loan") or body.get("loan")
    if isinstance(loan, dict):
        for key in ("HdrId", "hdr_id", "LoanHeaderId", "Id", "id"):
            v = loan.get(key)
            if v:
                return v
    for arr_key in ("Documents", "documents", "Items", "items",
                    "Transactions", "transactions"):
        arr = body.get(arr_key)
        if isinstance(arr, list) and arr:
            first = arr[0]
            if isinstance(first, dict):
                for key in ("HdrId", "hdr_id", "LoanHeaderId",
                            "LoanId", "loanId"):
                    v = first.get(key)
                    if v:
                        return v
    return None


def _shape_esign_pending(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one Vergent /api/esign/pending row → portal shape."""
    if not isinstance(record, dict):
        return None
    guid = (
        record.get("Id") or record.get("id")
        or record.get("Guid") or record.get("guid")
        or record.get("EsignId") or record.get("esignId")
    )
    if not guid:
        return None
    loan_id = (
        record.get("HdrId") or record.get("hdr_id")
        or record.get("LoanHeaderId") or record.get("loanHeaderId")
        or record.get("LoanId") or record.get("loanId")
    )
    public_id = (
        record.get("PublicLoanId") or record.get("publicLoanId")
        or record.get("PublicId") or record.get("publicId")
    )
    document_name = (
        record.get("DocumentName") or record.get("documentName")
        or record.get("Name") or record.get("name")
        or "Loan documents"
    )
    when = (
        record.get("CreatedDate") or record.get("createdDate")
        or record.get("RequestedDate") or record.get("requestedDate")
        or record.get("Date") or record.get("date")
    )
    return {
        "id": str(guid),
        "loanId": loan_id,
        "publicLoanId": public_id,
        "documentName": str(document_name),
        "createdDate": _format_iso(when),
    }


def _looks_like_guid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(re.match(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", value.strip()))


# Field names (case-insensitive) Vergent might use for the
# signing-session GUID embedded in the public hosted-signing URL
# (`https://shared.vergentlms.com/esign?g=<guid>`). Order matters —
# more specific names tried first. Anything matching one of these
# AND looking like a GUID wins; if none of these are present we
# fall back to "any GUID in the response that isn't the EsignId".
_SIGNING_URL_GUID_FIELDS = (
    "spcid", "spcguid", "spc",
    "signingurlid", "signingurl",
    "signingid", "signingguid",
    "signid", "signguid",
    "sessionid", "sessionguid",
    "pendingguid", "pendingid",
    "esignsessionid", "esignsessionguid",
    "guid",
)


def _resolve_signing_guid(esign_id: str,
                          sign_response: Any) -> Optional[str]:
    """Pick the most-likely URL-shaped signing GUID from a
    /esign/sign/{EsignId} response. Returns None if nothing
    matches — caller falls back to the EsignId itself."""
    if not isinstance(sign_response, dict):
        return None

    def _walk(obj: Any) -> Optional[str]:
        if not isinstance(obj, dict):
            return None
        # Prefer name-matched GUIDs
        for k, v in obj.items():
            if _looks_like_guid(v) and k.lower() in _SIGNING_URL_GUID_FIELDS:
                return v
        # Recurse into nested dicts
        for v in obj.values():
            if isinstance(v, dict):
                hit = _walk(v)
                if hit:
                    return hit
            elif isinstance(v, list):
                for item in v[:10]:
                    if isinstance(item, dict):
                        hit = _walk(item)
                        if hit:
                            return hit
        return None

    matched = _walk(sign_response)
    if matched:
        return matched

    # Last-resort: any GUID in the response that isn't the EsignId.
    candidates = _scan_for_guids(sign_response)
    for c in candidates:
        if c["guid"].lower() != str(esign_id).lower():
            return c["guid"]

    return None


def _scan_for_guids(value: Any, path: str = "",
                    out: Optional[List[Dict[str, str]]] = None,
                    depth: int = 0) -> List[Dict[str, str]]:
    """Walk an arbitrary JSON value and collect every string that
    looks like a GUID, paired with its dotted path. Used by the
    diagnostic surface so we can grep for the URL signing GUID
    in Vergent's response."""
    if out is None:
        out = []
    if depth > 4:
        return out
    guid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                         r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    if isinstance(value, str):
        if guid_re.match(value.strip()):
            out.append({"path": path or "<root>", "guid": value.strip()})
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_for_guids(v, f"{path}.{k}" if path else k, out, depth + 1)
    elif isinstance(value, list):
        for i, v in enumerate(value[:20]):  # cap to avoid log spam
            _scan_for_guids(v, f"{path}[{i}]", out, depth + 1)
    return out


def _fetch_pending_esign(cid: str) -> List[Dict[str, Any]]:
    """Fetch the list of pending e-sign requests for a customer.
    Returns shaped rows; empty list on any non-200 / unexpected
    shape so the caller can render an empty state cleanly."""
    if not cid:
        return []
    # V1_BASE already ends in /api/api — paths must NOT start with
    # another /api/ or IIS routes us to a 404. Vergent's swagger
    # documents this endpoint as /api/esign/pending/{cid}; the
    # leading /api/ is the swagger root, not part of the path.
    status, body = _v1_get(f"/esign/pending/{cid}")
    if status != 200:
        log.info("esign-pending status=%s cid=%s", status, cid)
        return []
    rows: List[Dict[str, Any]] = []
    if isinstance(body, list):
        rows = [r for r in body if isinstance(r, dict)]
    elif isinstance(body, dict):
        for key in ("Items", "Documents", "Pending", "Esigns",
                    "items", "documents", "pending", "esigns"):
            v = body.get(key)
            if isinstance(v, list):
                rows = [r for r in v if isinstance(r, dict)]
                break
    # Diagnostic: log the raw field set on the first row so we know
    # what Vergent is actually shipping. Removed when Phase 2 lands.
    if rows:
        log.info("esign-pending shape cid=%s count=%d keys=%s",
                 cid, len(rows), list(rows[0].keys())[:20])
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows:
        shaped = _shape_esign_pending(r)
        if not shaped or shaped["id"] in seen:
            continue
        seen.add(shaped["id"])
        out.append(shaped)

    # Vergent's /esign/pending list returns just { EsignId, EsignType,
    # CreatedDate } — no HdrId. Fan out one /esign/sign/{guid} call
    # per entry in parallel to extract the loan reference, so the
    # dashboard "Sign now" button can deep-link to the right loan.
    needs_hdr = [e for e in out if not e.get("loanId")]
    if needs_hdr:
        with ThreadPoolExecutor(max_workers=min(8, len(needs_hdr))) as ex:
            future_map = {
                ex.submit(_v1_get, f"/esign/sign/{entry['id']}"): entry
                for entry in needs_hdr
            }
            for fut, entry in future_map.items():
                try:
                    s, b = fut.result()
                    # Diagnostic: retain raw response on the entry
                    # so get_pending_esign can surface it. Removed
                    # once we know the right URL-GUID field.
                    entry["_signResponseStatus"] = s
                    entry["_signResponseBody"] = b
                    # Mark broken entries (500 from Vergent) so we
                    # can drop them — Vergent's /esign/pending
                    # sometimes lists stale records that fail when
                    # actually fetched. Picking one of these for
                    # the Sign now URL gives the customer a 500
                    # page on Vergent's side.
                    entry["_isValid"] = (s == 200)
                    hdr = _extract_hdr_id_from_esign_doc(b) if s == 200 else None
                    if hdr:
                        entry["loanId"] = hdr
                    else:
                        log.info("esign-enrich no_hdr id=%s status=%s shape=%s",
                                 entry["id"], s,
                                 list(b.keys())[:15] if isinstance(b, dict)
                                 else type(b).__name__)
                    signing_guid = _resolve_signing_guid(entry["id"], b) if s == 200 else None
                    if signing_guid:
                        entry["signingGuid"] = signing_guid
                        entry["signingUrl"] = (
                            "https://shared.vergentlms.com/esign?g="
                            + urllib.parse.quote(signing_guid)
                        )
                    elif s == 200:
                        # No alternate GUID in the response (Vergent
                        # likely uses the EsignId itself in the URL).
                        # Build the URL directly from EsignId so the
                        # frontend has it without falling through to
                        # the legacy fallback.
                        entry["signingUrl"] = (
                            "https://shared.vergentlms.com/esign?g="
                            + urllib.parse.quote(str(entry["id"]))
                        )
                except Exception as e:
                    entry["_isValid"] = False
                    log.warning("esign-enrich error id=%s err=%s",
                                entry["id"], type(e).__name__)
    # Drop broken entries (Vergent returns 500 on /esign/sign for
    # stale records its own /esign/pending list nonetheless still
    # advertises). Surfacing them caused the dashboard banner to
    # stick around after the customer had actually finished
    # signing — broken entries don't have a loanId so the per-loan
    # callout hid correctly, but the dashboard sees them as "still
    # pending". Return only valid entries; an empty list means no
    # actionable signature waiting.
    return [e for e in out if e.get("_isValid", True)]


def get_pending_esign(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-esign/pending — list e-sign requests still
    waiting on this customer's signature. Drives the dashboard
    banner + per-loan callout on the loan-detail page.

    Carries a temporary `_debug.signResponses` block — for each
    pending entry we log Vergent's /esign/sign/{EsignId} response
    shape + every GUID-like value found anywhere in it. That
    surfaces the URL-shaped GUID so the follow-up commit can
    populate the correct hosted-signing link. Dropped once we
    know which field to read.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"pending": [], "_debug": {"reason": "no_cid"}})

    enriched = _fetch_pending_esign(cid)
    sign_responses = []
    public = []
    for entry in enriched:
        sign_status = entry.pop("_signResponseStatus", None)
        sign_body = entry.pop("_signResponseBody", None)
        entry.pop("_isValid", None)
        public.append(entry)
        guid_candidates = _scan_for_guids(sign_body)
        # Strip the originating EsignId from the candidates list so
        # only NEW GUIDs (potential signing-session ids) remain.
        guid_candidates = [g for g in guid_candidates
                           if g["guid"].lower() != str(entry["id"]).lower()]
        sign_responses.append({
            "esignId": entry["id"],
            "upstreamStatus": sign_status,
            "bodyType": type(sign_body).__name__ if sign_body is not None else "None",
            "topKeys": (list(sign_body.keys())[:30]
                        if isinstance(sign_body, dict) else []),
            "guidCandidates": guid_candidates[:30],
            "rawSnippet": json.dumps(sign_body, default=str)[:1200]
                          if sign_body is not None else "",
        })

    log.info("esign-pending cid=%s rows=%d", cid, len(public))
    return _json_response(200, {
        "pending": public,
        "_debug": {
            "cid": cid,
            "signResponses": sign_responses,
        },
    })


def resend_esign(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-esign/resend — re-trigger Vergent's e-sign
    email for a specific loan the customer owns. Body:
    `{ "loanId": <int> }`.

    Ownership is enforced by walking _fetch_all_loans and matching
    the requested loanId — same pattern as get_loan_documents.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        body = {}
    requested = body.get("loanId")
    if requested in (None, ""):
        return _json_response(400, {"ok": False, "error": "missing_loanId"})

    shaped = _fetch_all_loans(cid)
    loan = next(
        (l for l in shaped
         if str(l.get("id")) == str(requested)
         or str(l.get("publicId") or "") == str(requested)),
        None,
    )
    if not loan:
        return _json_response(404, {"ok": False, "error": "loan_not_found"})

    hdr_id = loan.get("id")
    # Prefer the v1 POST sendesign — properly REST-shaped and the
    # description explicitly says it identifies Signasure docs and
    # routes them, rather than re-firing whatever the legacy
    # GET endpoint defaulted to. Fall back to the GET path if the
    # POST returns a non-2xx so we don't regress on tenants that
    # only support the older endpoint.
    attempts = []
    post_status, _post_parsed, post_raw = _v1_request(
        "POST", f"/V1/customer/{cid}/docs/sendesign/{hdr_id}",
        return_raw=True,
    )
    attempts.append({
        "method": "POST",
        "path": f"/V1/customer/{cid}/docs/sendesign/{hdr_id}",
        "status": post_status,
        "rawSnippet": (post_raw if isinstance(post_raw, str) else str(post_raw or ""))[:300],
    })
    status = post_status
    if status not in (200, 204):
        log.info("esign-resend POST sendesign status=%s hdr=%s; falling back to GET",
                 status, hdr_id)
        get_status, _get_parsed, get_raw = _v1_request(
            "GET", f"/esign/sendEsignDocs/{hdr_id}",
            return_raw=True,
        )
        attempts.append({
            "method": "GET",
            "path": f"/esign/sendEsignDocs/{hdr_id}",
            "status": get_status,
            "rawSnippet": (get_raw if isinstance(get_raw, str) else str(get_raw or ""))[:300],
        })
        status = get_status
    if status not in (200, 204):
        log.warning("esign-resend non-2xx status=%s hdr=%s attempts=%d",
                    status, hdr_id, len(attempts))
        return _json_response(502, {
            "ok": False,
            "error": "vergent_error",
            "upstreamStatus": status,
            "_debug": {"hdrId": hdr_id, "attempts": attempts},
        })
    return _json_response(200, {"ok": True})


def _esign_owns_loan(cid: str, loan_id: Any) -> Optional[Dict[str, Any]]:
    """Return the shaped loan if this customer owns it, else None.
    Shared ownership check used by document-fetch + submit handlers."""
    if loan_id in (None, ""):
        return None
    shaped = _fetch_all_loans(cid)
    return next(
        (l for l in shaped
         if str(l.get("id")) == str(loan_id)
         or str(l.get("publicId") or "") == str(loan_id)),
        None,
    )


def get_esign_document(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-esign/document?loanId=N or ?esignId=GUID — fetch
    the unsigned document set via Vergent v1 /esign/sign/{guid}.

    Either query param works:
      - loanId: looks up the pending esign GUID for this loan from
        the customer's /esign/pending list, then proxies through
      - esignId: direct fetch; ownership enforced by checking the
        GUID is in the customer's pending list

    Returns Vergent's response body so the modal can render
    whichever shape comes back (HTML, JSON metadata, etc.).
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "no_customer_id"})

    qs = event.get("queryStringParameters") or {}
    requested_loan = (qs or {}).get("loanId") if isinstance(qs, dict) else None
    requested_esign = (qs or {}).get("esignId") if isinstance(qs, dict) else None
    if not requested_loan and not requested_esign:
        return _json_response(400, {"error": "missing_id"})

    pending = _fetch_pending_esign(cid)

    match = None
    loan = None
    if requested_esign:
        match = next(
            (p for p in pending if str(p.get("id")) == str(requested_esign)),
            None,
        )
        if match and match.get("loanId"):
            loan = _esign_owns_loan(cid, match["loanId"]) or {}
    else:
        loan = _esign_owns_loan(cid, requested_loan)
        if not loan:
            return _json_response(404, {"error": "loan_not_found"})
        match = next(
            (p for p in pending
             if str(p.get("loanId")) == str(loan.get("id"))
             or str(p.get("publicLoanId") or "") == str(loan.get("publicId") or "")),
            None,
        )

    if not match:
        return _json_response(404, {"error": "no_pending_signature"})

    esign_id = match["id"]
    status, body = _v1_get(f"/esign/sign/{esign_id}")
    log.info("esign-fetch loan=%s esign=%s status=%s body_type=%s",
             (loan or {}).get("id"), esign_id, status, type(body).__name__)
    if status not in (200, 204):
        return _json_response(502, {
            "error": "vergent_error",
            "upstreamStatus": status,
        })

    return _json_response(200, {
        "esignId": esign_id,
        "loanId": (loan or {}).get("id") or match.get("loanId"),
        "publicLoanId": (loan or {}).get("publicId") or match.get("publicLoanId"),
        "document": body,
    })


def submit_esign(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-esign/sign — finalize an in-portal signature.

    Body accepts either { loanId, signerName, agreed } OR
    { esignId, signerName, agreed }. esignId is the more reliable
    key since Vergent's /esign/pending list doesn't always include
    the loan reference.

    Posts to Vergent v1 /api/V1/loan/{HdrId}/signingdata when we
    can resolve a HdrId; falls back to
    /api/V1/customer/{cid}/signingdata otherwise. Surfaces
    upstreamStatus + upstreamBody on failure.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        body = {}
    requested_loan = body.get("loanId")
    requested_esign = body.get("esignId")
    signer_name = (body.get("signerName") or "").strip()
    agreed = bool(body.get("agreed"))
    if not requested_loan and not requested_esign:
        return _json_response(400, {"ok": False, "error": "missing_id"})
    if not signer_name:
        return _json_response(400, {"ok": False, "error": "missing_signerName"})
    if not agreed:
        return _json_response(400, {"ok": False, "error": "consent_required"})

    pending = _fetch_pending_esign(cid)

    match = None
    loan = None
    if requested_esign:
        match = next(
            (p for p in pending if str(p.get("id")) == str(requested_esign)),
            None,
        )
        if match and match.get("loanId"):
            loan = _esign_owns_loan(cid, match["loanId"]) or {}
    else:
        loan = _esign_owns_loan(cid, requested_loan)
        if not loan:
            return _json_response(404, {"ok": False, "error": "loan_not_found"})
        match = next(
            (p for p in pending
             if str(p.get("loanId")) == str(loan.get("id"))
             or str(p.get("publicLoanId") or "") == str(loan.get("publicId") or "")),
            None,
        )
    if not match:
        return _json_response(409, {"ok": False, "error": "no_pending_signature"})

    hdr_id = (loan or {}).get("id") or match.get("loanId")
    esign_id = match["id"]

    http_ctx = (event.get("requestContext") or {}).get("http") or {}
    headers_raw = event.get("headers") or {}
    user_agent = (
        http_ctx.get("userAgent")
        or headers_raw.get("user-agent") or headers_raw.get("User-Agent")
        or ""
    )
    source_ip = (
        http_ctx.get("sourceIp")
        or headers_raw.get("x-forwarded-for") or headers_raw.get("X-Forwarded-For")
        or ""
    )
    if "," in source_ip:
        source_ip = source_ip.split(",")[0].strip()
    signed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    payload = {
        "EsignId": esign_id,
        "HdrId": hdr_id,
        "CustomerId": cid,
        "SignerName": signer_name,
        "Signature": signer_name,
        "SignedDate": signed_at,
        "IpAddress": source_ip,
        "UserAgent": user_agent[:300],
        "Accepted": True,
    }

    attempts = []
    final_status = None
    final_parsed = None
    final_raw = ""

    if hdr_id:
        s, parsed, raw = _v1_request(
            "POST", f"/V1/loan/{hdr_id}/signingdata",
            body=payload, return_raw=True,
        )
        attempts.append({
            "path": f"/V1/loan/{hdr_id}/signingdata",
            "status": s,
            "rawSnippet": (raw if isinstance(raw, str) else str(raw or ""))[:300],
        })
        final_status, final_parsed, final_raw = s, parsed, raw

    if final_status not in (200, 201, 204):
        # Fall back to the customer-scoped submit (works without HdrId).
        s, parsed, raw = _v1_request(
            "POST", f"/V1/customer/{cid}/signingdata",
            body=payload, return_raw=True,
        )
        attempts.append({
            "path": f"/V1/customer/{cid}/signingdata",
            "status": s,
            "rawSnippet": (raw if isinstance(raw, str) else str(raw or ""))[:300],
        })
        final_status, final_parsed, final_raw = s, parsed, raw

    log.info("esign-submit loan=%s esign=%s final_status=%s attempts=%d",
             hdr_id, esign_id, final_status, len(attempts))
    if final_status not in (200, 201, 204):
        log.warning("esign-submit non-2xx loan=%s status=%s body=%r",
                    hdr_id, final_status, (final_raw or "")[:400])
        return _json_response(502, {
            "ok": False,
            "error": "vergent_error",
            "upstreamStatus": final_status,
            "upstreamBody": (final_raw or "")[:600],
            "_debug": {"attempts": attempts},
        })

    if hdr_id:
        try:
            _v1_request("PUT", f"/V1/loan/{hdr_id}/signingstatus",
                        body={"Status": "Complete", "EsignId": esign_id})
        except Exception as exc:
            log.info("esign-submit status-put error loan=%s err=%s",
                     hdr_id, type(exc).__name__)

    return _json_response(200, {"ok": True, "result": final_parsed})


# ─────────────────────────────────────────
# Admin customer search (cif-admin Cognito group)
# ─────────────────────────────────────────
# Called by cif-dashboard's admin UI when an operator searches
# for a customer to support / impersonate. Auth gate is the same
# cif-admin group check that /api/admin/plaid/* uses.
#
# Two source paths, dispatched on the ?source= query param:
#
#   source=portal (default) — searches the Cognito User Pool.
#     Returns only customers who actually registered for the portal
#     at apply.cashinflash.com. Each row carries Cognito UserStatus
#     (CONFIRMED / UNCONFIRMED) + signup date.
#
#   source=vergent — searches the LMS's full customer base via the
#     Vergent v1 API. Returns every customer that exists in
#     Vergent regardless of portal-account status. Each row carries
#     the Vergent customer status + store.
#
# Search heuristics (apply to both sources):
#   - q is 4-8 digits → customerId lookup (exact)
#   - q contains "@"  → email lookup (prefix match on portal,
#                       exact-match query on Vergent)
#   - otherwise       → last-name lookup (prefix match)
#
# Cognito ListUsers Filter only supports `=` and `^=` (prefix)
# on standard attributes. Custom attributes (like
# custom:vergentCustomerId) can't be filtered server-side, so the
# customerId path on the portal source falls back to a full pool
# scan via auth_mfa._find_cognito_user_by_vergent_id. OK while
# the pool is small (< ~10k users); Phase 2 will add a DDB
# index keyed on vergentCustomerId to make this O(1).

def search_admin_customers(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/admin/customers/search?q=<term>&source=portal|vergent

    For source=portal an empty q is allowed and returns the first
    100 portal users (no filter). For source=vergent an empty q
    returns 400 — listing the LMS's full base would be ~50k+ rows.
    """
    claims = _claims(event)
    err = plaid._require_admin_group(claims)
    if err:
        return err

    qs = event.get("queryStringParameters") or {}
    q = ((qs or {}).get("q") or "").strip()

    # Default to portal — the safer choice. Operators usually
    # want portal customers; the Vergent tab is for cross-checking
    # against the LMS's broader population.
    source = ((qs or {}).get("source") or "portal").strip().lower()
    if source not in ("portal", "vergent"):
        source = "portal"

    if source == "vergent":
        if not q:
            return _json_response(400, {"error": "missing_q"})
        rows, err_detail = _search_vergent_customers(q)
    else:
        rows, err_detail = _search_portal_customers(q)

    # Online/offline dot data for the customers page (best-effort; never
    # affects the customer list itself).
    try:
        _annotate_presence(rows)
    except Exception:
        pass

    body = {"q": q, "source": source, "results": rows}
    if err_detail:
        # Surface the upstream error so the dashboard can display
        # it instead of silently rendering "no matches" on what is
        # actually a permissions / API failure.
        body["error"] = err_detail
    return _json_response(200, body)


def _search_portal_customers(q: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Cognito User Pool search. Returns (rows, error_detail). When
    `q` is empty, lists all portal users (capped at 100). When `q`
    is digits, falls back to a full pool scan via auth_mfa's
    helper. Otherwise issues a Cognito ListUsers Filter call."""
    # Lazy import — see top-level note. auth_mfa's module body reads
    # required Cognito env vars with os.environ[...], so importing
    # it here keeps non-auth Lambdas (payments) from KeyError-ing on
    # cold start.
    from handlers import auth_mfa
    # Empty q → list-all mode. Used by the Customers tab to show
    # every portal-registered user when no search is in progress.
    if not q:
        rows: List[Dict[str, Any]] = []
        token: Optional[str] = None
        try:
            while len(rows) < 100:
                kwargs: Dict[str, Any] = {
                    "UserPoolId": auth_mfa.USER_POOL_ID,
                    "Limit": 60,
                }
                if token:
                    kwargs["PaginationToken"] = token
                resp = auth_mfa.cognito.list_users(**kwargs)
                for u in resp.get("Users") or []:
                    attrs = {a["Name"]: a["Value"]
                             for a in u.get("Attributes", [])}
                    rows.append(_shape_cognito_customer_row({
                        "Username": u.get("Username"),
                        "Attrs": attrs,
                        "Status": u.get("UserStatus"),
                        "UserCreateDate": u.get("UserCreateDate"),
                    }))
                    if len(rows) >= 100:
                        break
                token = resp.get("PaginationToken")
                if not token:
                    break
        except Exception as exc:
            log.warning("portal customer list-all list_users failed: %s", exc)
            return rows, f"{type(exc).__name__}: {str(exc)[:200]}"
        # Sort newest signups first so the most recent registrations
        # are visible at the top.
        rows.sort(key=lambda r: r.get("signupTs") or 0, reverse=True)
        return rows, None

    digits_only = q.isdigit()

    if digits_only and 4 <= len(q) <= 8:
        try:
            user = auth_mfa._find_cognito_user_by_vergent_id(q)
        except Exception as exc:
            log.warning("portal cid scan failed q=%s: %s", q, exc)
            return [], f"{type(exc).__name__}: {str(exc)[:200]}"
        if not user:
            return [], None
        return [_shape_cognito_customer_row(user)], None

    safe_q = q.replace('"', "")
    if "@" in q:
        cognito_filter = f'email ^= "{safe_q}"'
    else:
        cognito_filter = f'family_name ^= "{safe_q}"'

    try:
        resp = auth_mfa.cognito.list_users(
            UserPoolId=auth_mfa.USER_POOL_ID,
            Filter=cognito_filter,
            Limit=25,
        )
    except Exception as exc:
        log.warning("portal customer search list_users failed filter=%r: %s",
                    cognito_filter, exc)
        return [], f"{type(exc).__name__}: {str(exc)[:200]}"

    rows: List[Dict[str, Any]] = []
    for u in resp.get("Users") or []:
        attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
        rows.append(_shape_cognito_customer_row({
            "Username": u.get("Username"),
            "Attrs": attrs,
            "Status": u.get("UserStatus"),
            "UserCreateDate": u.get("UserCreateDate"),
        }))
    return rows, None


def _search_vergent_customers(q: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Vergent v1 API search. Returns (rows, error_detail). Capped
    at 25 rows."""
    tok = _get_v1_token()
    if not tok:
        log.warning("vergent customer search: no v1 token")
        return [], "vergent_unavailable"

    digits_only = q.isdigit()
    if digits_only and 4 <= len(q) <= 8:
        path = f"/V1/GetCustomer/{q}"
        status, body, _raw = _http(
            f"{V1_BASE}{path}", "GET", headers={"Token": tok})
        if status != 200 or not isinstance(body, dict):
            return [], None
        return [_shape_vergent_customer_row(body)], None

    if "@" in q:
        path = f"/V1/GetCustomers?email={urllib.parse.quote(q)}"
    else:
        path = f"/V1/GetCustomers?lastName={urllib.parse.quote(q)}"

    status, body, _raw = _http(
        f"{V1_BASE}{path}", "GET", headers={"Token": tok})
    if status != 200:
        log.warning("vergent customer search v1 status=%s path=%s",
                    status, path)
        return [], f"vergent_v1_status_{status}"

    items = body if isinstance(body, list) else None
    if isinstance(body, dict):
        items = (body.get("Items") or body.get("Customers")
                 or body.get("customers") or [])
    if not isinstance(items, list):
        items = []

    return ([_shape_vergent_customer_row(it) for it in items[:25]
            if isinstance(it, dict)]), None


def _shape_cognito_customer_row(user: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a Cognito user record to a portal-source search row."""
    attrs = user.get("Attrs") or {}
    cid = attrs.get("custom:vergentCustomerId") or ""
    email = (attrs.get("email") or "").strip()
    phone = (attrs.get("phone_number") or "").strip()
    first = (attrs.get("given_name") or "").strip()
    last = (attrs.get("family_name") or "").strip()
    # Legacy accounts onboarded before mint-link carried the last name were
    # created with an empty family_name → the page showed first-only. Backfill
    # the DISPLAY from Vergent when family_name is missing. Best-effort; only
    # fires for those older accounts (new signups store family_name), so the
    # common list-all path stays free of per-row Vergent calls.
    if (not last) and cid:
        try:
            from handlers import auth_mfa as _am
            _cu = _am._vergent_get_customer(str(cid)) or {}
            last = (_cu.get("LastName") or _cu.get("Last") or _cu.get("LName") or "").strip()
            if not first:
                first = (_cu.get("FirstName") or _cu.get("First") or _cu.get("FName") or "").strip()
        except Exception:
            pass
    cognito_status = (user.get("Status") or "").strip() or None
    created = user.get("UserCreateDate")
    # Operator-facing format: MM/DD/YYYY at h:mm AM/PM, in Pacific (the
    # business' timezone) since Cognito stamps UserCreateDate in UTC. Falls
    # back to a plain MM/DD/YYYY date if tz data is unavailable.
    signup_at = None
    if created is not None:
        try:
            from zoneinfo import ZoneInfo
            signup_at = created.astimezone(
                ZoneInfo("America/Los_Angeles")).strftime("%m/%d/%Y at %I:%M %p")
        except Exception:
            try:
                signup_at = created.strftime("%m/%d/%Y")
            except Exception:
                signup_at = str(created)[:10]
    # Numeric sort key (epoch) so list-all sorts newest-first regardless of the
    # human-friendly MM/DD/YYYY signupAt string.
    signup_ts = 0
    try:
        if created is not None:
            signup_ts = int(created.timestamp())
    except Exception:
        signup_ts = 0
    return {
        "source": "portal",
        "customerId": str(cid) if cid else None,
        "cognitoSub": attrs.get("sub") or user.get("Username"),
        "firstName": first or None,
        "lastName": last or None,
        "fullName": (" ".join(p for p in (first, last) if p)).strip() or None,
        "email": email or None,
        "phoneLast4": (phone[-4:] if phone else None),
        "statusName": cognito_status,
        "signupAt": signup_at,
        "signupTs": signup_ts,
    }


def _shape_vergent_customer_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a Vergent customer record to a vergent-source search row."""
    cid = (rec.get("customerId") or rec.get("CustomerId")
           or rec.get("id") or rec.get("Id") or "")
    email = (rec.get("email") or rec.get("Email") or "").strip()
    phone = (rec.get("phoneNumber") or rec.get("PhoneNumber")
             or rec.get("phone") or rec.get("Phone") or "").strip()
    first = (rec.get("firstName") or rec.get("FirstName") or "").strip()
    last = (rec.get("lastName") or rec.get("LastName") or "").strip()
    status = (rec.get("statusName") or rec.get("StatusName")
              or rec.get("status") or "").strip() or None
    store = (rec.get("storeName") or rec.get("StoreName")
             or rec.get("store") or "").strip() or None
    return {
        "source": "vergent",
        "customerId": str(cid) if cid else None,
        "firstName": first or None,
        "lastName": last or None,
        "fullName": (" ".join(p for p in (first, last) if p)).strip() or None,
        "email": email or None,
        "phoneLast4": (phone[-4:] if phone else None),
        "statusName": status,
        "storeName": store,
    }


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════
# FAST RE-APPLY — native in-portal re-loan for returning customers.
#
# Two routes:
#   GET  /api/my-reapply/prefill  -> editable identity + linked banks
#   POST /api/my-reapply/submit   -> hand cif-apply a re-loan (RL)
#
# Trust boundary: the customer identity (Vergent cid) is taken ONLY from
# the JWT, the Plaid access token ONLY from our DynamoDB scoped to that
# cid, and the base profile ONLY from Vergent scoped to that cid. The
# client supplies just the requested amount, which linked bank to use,
# and edits to its own address/employer/contact. A customer can never
# submit a re-loan as anyone but themselves.
# ═════════════════════════════════════════════════════════════════
def _mask_tail(s: str, keep: int = 4) -> str:
    """Mask all but the last `keep` chars of a sensitive value."""
    s = (s or "").strip()
    if len(s) <= keep:
        return s
    return "•••• " + s[-keep:]


def _reapply_customer_info(cid: str, claims: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort identity / employment / bank pull for a returning
    customer, keyed to the JWT-resolved cid. Tolerates PascalCase and
    snake_case Vergent shapes; falls back to Cognito claims."""
    info = {
        "firstName": (claims.get("given_name") or "").strip(),
        "lastName": (claims.get("family_name") or "").strip(),
        "email": (claims.get("email") or "").strip(),
        "phone": (claims.get("phone_number") or "").strip(),
        "dob": "", "address": "", "address2": "", "city": "", "state": "",
        "zip": "", "employer": "", "grossPay": "", "payDay": "",
        "lastPayDate": "", "payFrequency": "", "sourceOfIncome": "",
        "bankName": "", "routingNumber": "", "accountNumber": "",
    }
    try:
        status, data = _v1_get(f"/V1/GetCustomerData/{cid}")
    except Exception as exc:  # pragma: no cover - network
        log.warning("reapply GetCustomerData failed cid=%s: %s", cid, exc)
        status, data = 0, None
    if status != 200 or not isinstance(data, dict):
        return info

    def g(d, *keys):
        if not isinstance(d, dict):
            return ""
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    cust = data.get("cust") if isinstance(data.get("cust"), dict) else data
    info["firstName"] = g(cust, "FirstName", "firstName", "first_name") or info["firstName"]
    info["lastName"] = g(cust, "LastName", "lastName", "last_name") or info["lastName"]
    info["email"] = g(cust, "EmailAddr", "emailAddr", "Email", "email") or info["email"]
    dob_raw = g(cust, "BirthDate", "birthDate", "dob")
    if "T" in dob_raw:
        info["dob"] = dob_raw.split("T", 1)[0]
    elif dob_raw:
        info["dob"] = dob_raw

    addresses = data.get("custAddresses") or data.get("CustAddresses") or []
    if isinstance(addresses, list) and addresses:
        a = next((x for x in addresses if isinstance(x, dict)
                  and (x.get("is_primary") or x.get("IsPrimary"))), None) \
            or next((x for x in addresses if isinstance(x, dict)), None)
        if a:
            info["address"] = g(a, "addr1", "Addr1")
            info["address2"] = g(a, "addr2", "Addr2")
            info["city"] = g(a, "city", "City")
            info["state"] = g(a, "abbrev", "Abbrev", "state", "State")
            info["zip"] = g(a, "zip", "Zip")

    phones = data.get("custPhones") or data.get("CustPhones") or []
    if isinstance(phones, list) and phones:
        p = next((x for x in phones if isinstance(x, dict)
                  and (x.get("is_primary") or x.get("IsPrimary"))), None) \
            or next((x for x in phones if isinstance(x, dict)), None)
        if p:
            info["phone"] = g(p, "number", "Number") or info["phone"]

    emps = data.get("custEmps") or data.get("CustEmps") or []
    if isinstance(emps, list) and emps:
        e = emps[0] if isinstance(emps[0], dict) else {}
        info["employer"] = g(e, "Name", "name", "employer_name")
        pay = g(e, "PayAmount", "pay_amount")
        if pay:
            try:
                info["grossPay"] = str(float(pay) or "")
            except (TypeError, ValueError):
                pass
        prev = g(e, "PrevPayDate", "prev_pay_date")
        if "T" in prev:
            info["lastPayDate"] = prev.split("T", 1)[0]
        nxt = g(e, "NextPayDate", "next_pay_date")
        if "T" in nxt:
            info["payDay"] = nxt.split("T", 1)[0]

    banks = data.get("custBanks") or data.get("CustBanks") or []
    if isinstance(banks, list) and banks:
        b = banks[0] if isinstance(banks[0], dict) else {}
        info["bankName"] = g(b, "Name", "name")
        info["routingNumber"] = g(b, "RoutingNum", "routing_num")
        info["accountNumber"] = g(b, "AccountNum", "account_num")
    return info


def _reapply_application_data(info: Dict[str, Any], amount: int) -> Dict[str, Any]:
    """Shape the gathered info into the applicationData dict cif-apply's
    /submit pipeline expects (same keys as server.py's record)."""
    return {
        "firstName": info.get("firstName", ""), "middleName": "",
        "lastName": info.get("lastName", ""),
        "loanAmount": str(amount),
        "dob": info.get("dob", ""),
        "address": info.get("address", ""), "address2": info.get("address2", ""),
        "city": info.get("city", ""), "state": info.get("state", ""),
        "zip": info.get("zip", ""),
        "phone": info.get("phone", ""), "email": info.get("email", ""),
        "sourceOfIncome": info.get("sourceOfIncome", ""),
        "employer": info.get("employer", ""),
        "payFrequency": info.get("payFrequency", ""),
        "payDay": info.get("payDay", ""),
        "lastPayDate": info.get("lastPayDate", ""),
        "paymentMethod": "Direct Deposit",
        "grossPay": info.get("grossPay", ""),
        "accountType": "Checking",
        "routingNumber": info.get("routingNumber", ""),
        "accountNumber": info.get("accountNumber", ""),
        "bankName": info.get("bankName", ""),
        "housingStatus": "", "bankruptcy": "", "military": "",
        "bankMethod": "Plaid (Connected)",
    }


def _reapply_vergent_edits(orig: Dict[str, Any],
                           edits: Dict[str, Any]) -> Dict[str, Any]:
    """Build the {phone?, address?} of fields the customer actually changed,
    for direct push to the existing Vergent record (cif-apply applies it via
    its V1 client). Case-insensitive diff so a title-cased "123 Main St" vs
    on-file "123 main st" isn't treated as a change. Employer has no Vergent
    write endpoint, so it stays on the application for the operator."""
    out: Dict[str, Any] = {}
    if not isinstance(edits, dict):
        return out

    def n(s):
        return (s or "").strip().lower()

    new_phone = _digits_only(edits.get("phone") or "")[-10:]
    if len(new_phone) == 10 and new_phone != _digits_only(orig.get("phone") or "")[-10:]:
        out["phone"] = new_phone

    addr_keys = ("address", "address2", "city", "state", "zip")
    if any(isinstance(edits.get(k), str) and n(edits.get(k))
           and n(edits.get(k)) != n(orig.get(k)) for k in addr_keys):
        out["address"] = {
            "addr1": (edits.get("address") or orig.get("address") or "").strip(),
            "addr2": (edits.get("address2") or orig.get("address2") or "").strip(),
            "city": (edits.get("city") or orig.get("city") or "").strip(),
            "state": (edits.get("state") or orig.get("state") or "").strip().upper()[:2],
            "zip": _digits_only(edits.get("zip") or orig.get("zip") or "")[:9],
        }
    return out


def get_reapply_prefill(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-reapply/prefill — editable identity + linked banks for
    the native re-apply flow (screens 1 + 2)."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})
    info = _reapply_customer_info(cid, claims)
    try:
        conns = plaid._list_connections(cid)
    except Exception as exc:  # pragma: no cover - network
        log.warning("reapply list_connections failed cid=%s: %s", cid, exc)
        conns = []
    banks = [{
        "itemId": c.get("itemId", ""),
        "institutionName": c.get("institutionName") or "Bank",
        "accountMask": c.get("accountMask") or "",
        "linkedAt": c.get("linkedAt") or "",
    } for c in conns if c.get("itemId")]
    # First-time vs returning — drives the page title ("your first loan" vs
    # "another loan"). Safe default on error: assume returning.
    try:
        has_prior_loans = len(_fetch_all_loans(cid)) > 0
    except Exception as exc:  # pragma: no cover - network
        log.warning("reapply prior-loans check failed cid=%s: %s", cid, exc)
        has_prior_loans = True
    return _json_response(200, {
        "ok": True,
        "hasPriorLoans": has_prior_loans,
        "prefill": {
            "firstName": info.get("firstName", ""),
            "lastName": info.get("lastName", ""),
            "email": info.get("email", ""),
            "phone": info.get("phone", ""),
            "address": info.get("address", ""),
            "address2": info.get("address2", ""),
            "city": info.get("city", ""),
            "state": info.get("state", ""),
            "zip": info.get("zip", ""),
            "employer": info.get("employer", ""),
        },
        "banks": banks,
        "hasBankOnFile": bool(banks),
        "bankOnFile": {
            "bankName": info.get("bankName", ""),
            # Routing numbers are public bank identifiers — show in full.
            # Account number is sensitive — mask to the last 4.
            "routingNumber": info.get("routingNumber", ""),
            "accountNumber": _mask_tail(info.get("accountNumber", "")),
        },
        "minAmount": REAPPLY_MIN_AMOUNT,
        "maxAmount": REAPPLY_MAX_AMOUNT,
    })


def submit_reapply(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-reapply/submit — assemble the application server-side
    and hand it to cif-apply's additive intake endpoint.

    Body: { "amount": 255, "plaidItemId": "...", "edits": {address, ...} }
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        body = {}

    try:
        amount = int(round(float(body.get("amount") or 0)))
    except (TypeError, ValueError):
        amount = 0
    if amount < REAPPLY_MIN_AMOUNT or amount > REAPPLY_MAX_AMOUNT:
        return _json_response(400, {
            "ok": False, "error": "bad_amount",
            "detail": f"Amount must be ${REAPPLY_MIN_AMOUNT}–${REAPPLY_MAX_AMOUNT}.",
        })

    # Resolve the chosen linked bank's access token SERVER-SIDE, scoped to
    # this customer. Never trust a token from the client.
    try:
        conns = plaid._list_connections(cid)
    except Exception as exc:  # pragma: no cover - network
        log.warning("reapply submit list_connections failed cid=%s: %s", cid, exc)
        conns = []
    item_id = (body.get("plaidItemId") or "").strip()
    chosen = None
    if item_id:
        chosen = next((c for c in conns if c.get("itemId") == item_id), None)
    if not chosen and conns:
        chosen = conns[0]  # most-recently linked
    if not chosen:
        return _json_response(409, {
            "ok": False, "error": "needs_bank",
            "detail": "No linked bank on file. Connect your bank first.",
        })
    item_id = chosen.get("itemId", "")
    institution = chosen.get("institutionName") or ""
    access_token = plaid._get_access_token(cid, item_id)
    if not access_token:
        return _json_response(409, {
            "ok": False, "error": "needs_bank",
            "detail": "Could not read your linked bank. Please reconnect it.",
        })

    # Base profile from Vergent, overlaid with the customer's own edits.
    info = _reapply_customer_info(cid, claims)
    orig_info = dict(info)  # snapshot before overlay, for change detection
    edits = body.get("edits") or {}
    if isinstance(edits, dict):
        for k in ("address", "address2", "city", "state", "zip",
                  "employer", "phone", "email"):
            v = edits.get(k)
            if isinstance(v, str) and v.strip():
                info[k] = v.strip()
    app_data = _reapply_application_data(info, amount)

    # Carry the customer's chosen on-file debit card into the application
    # so the dashboard's Debit Card tab shows which card they selected.
    dc = body.get("debitCard")
    if isinstance(dc, dict) and dc.get("last4"):
        app_data["debitCard"] = {
            "brand": str(dc.get("brand") or "")[:32],
            "last4": str(dc.get("last4") or "")[-4:],
            "cardholder": str(dc.get("cardholder") or "")[:80],
            "expMonth": str(dc.get("expMonth") or ""),
            "expYear": str(dc.get("expYear") or ""),
            "vergentCardId": str(dc.get("vergentCardId") or ""),
            "onFile": True,
        }

    # Bank-match check (Plaid-connected account vs the account on file in
    # Vergent). The customer is warned but never blocked; we stamp the result
    # so the dashboard flags a mismatch for the operator to confirm the exact
    # account before funding (Vergent exposes no API to overwrite it).
    bm = body.get("bankMatch")
    if isinstance(bm, dict):
        conn4 = "".join(c for c in str(bm.get("connectedLast4") or "") if c.isdigit())[-4:]
        file4 = "".join(c for c in str(bm.get("onFileLast4") or "") if c.isdigit())[-4:]
        if conn4 and file4:
            app_data["bankMatch"] = {
                "matches": bool(bm.get("matches")),
                "connectedLast4": conn4,
                "onFileLast4": file4,
            }

    # Edits to push directly into the existing Vergent profile (cif-apply
    # applies them via its V1 client). Phone is Telnyx-verified above.
    vergent_edits = _reapply_vergent_edits(orig_info, edits)

    creds = plaid._load_creds() or {}
    plaid_creds = {
        "clientId": creds.get("clientId", ""),
        "secret": creds.get("secret", ""),
        "env": creds.get("env") or "production",
    }
    payload = {
        "secret": REAPPLY_SHARED_SECRET,
        "amount": amount,
        "applicationData": app_data,
        "vergentCustomerId": cid,
        "plaidAccessToken": access_token,
        "plaidCreds": plaid_creds,
        "plaidItemId": item_id,
        "plaidInstitutionName": institution,
        "vergentEdits": vergent_edits,
    }
    status, parsed, raw = _http(CIF_APPLY_REAPPLY_URL, "POST",
                                body=payload, timeout=25)
    if status == 200 and isinstance(parsed, dict) and parsed.get("ok"):
        log.info("reapply ok cid=%s amount=%s fb=%s",
                 cid, amount, parsed.get("firebaseId"))
        return _json_response(200, {
            "ok": True,
            "firebaseId": parsed.get("firebaseId"),
            "amount": amount,
        })
    log.warning("reapply handoff failed cid=%s status=%s body=%r",
                cid, status, (raw or "")[:300])
    return _json_response(502, {
        "ok": False, "error": "submit_failed",
        "detail": "We couldn't submit your application. Please try again.",
    })


def get_reapply_my_status(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/my-reapply/status — lifecycle of this customer's latest
    re-loan so the dashboard can show a pending / declined card. cid is
    taken from the JWT; we ask cif-apply for the report's state. Fails
    soft (state="none") so a hiccup never breaks the dashboard."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})
    status_url = CIF_APPLY_REAPPLY_URL + "-status"  # …/api/portal-reapply-status
    try:
        st, parsed, _raw = _http(status_url, "POST", body={
            "secret": REAPPLY_SHARED_SECRET, "customer_id": cid,
        }, timeout=12)
    except Exception as exc:  # pragma: no cover - network
        log.warning("reapply status lookup failed cid=%s: %s", cid, exc)
        return _json_response(200, {"ok": True, "state": "none"})
    if st != 200 or not isinstance(parsed, dict) or not parsed.get("ok") \
            or not parsed.get("found"):
        return _json_response(200, {"ok": True, "state": "none"})
    if parsed.get("funded"):
        state = "funded"        # active-loan card takes over; no RL card
    elif parsed.get("declined"):
        # Show the "not approved" card for at most 24h after submission,
        # then let it clear (and the Apply CTAs return) if they haven't
        # re-applied.
        sub_ms = parsed.get("submittedAt") or 0
        try:
            age_ms = (time.time() * 1000) - float(sub_ms)
        except (TypeError, ValueError):
            age_ms = 0
        state = "declined" if (sub_ms and age_ms < 30 * 60 * 1000) else "none"
    else:
        state = "pending"
    return _json_response(200, {
        "ok": True, "state": state,
        "amount": parsed.get("amount"),
        "submittedAt": parsed.get("submittedAt"),
    })


SUPPORT_REASONS = {
    "general": "General question",
    "loan": "Loan question",
    "payment": "Payment question",
    "technical": "Technical support",
    "other": "Other",
}


def submit_support(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-support — a signed-in customer sends a support message.
    Identity comes from the JWT (no re-typing); emailed to info@cashinflash.com
    via Resend, with reply-to set to the customer so the team can reply directly."""
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    reason = SUPPORT_REASONS.get(str(body.get("reason") or "").strip().lower(), "General question")
    message = str(body.get("message") or "").strip()
    if len(message) < 2:
        return _json_response(400, {"error": "empty_message"})
    message = message[:5000]
    name = ((claims.get("given_name") or "") + " " + (claims.get("family_name") or "")).strip() or "(no name)"
    email = (claims.get("email") or "").strip()
    phone = (claims.get("phone_number") or "").strip()

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    row = ("<tr><td style=\"padding:4px 14px 4px 0;color:#6b7280\">{}</td>"
           "<td style=\"color:#0f2a20\"><b>{}</b></td></tr>")
    html = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif\">"
        "<h2 style=\"margin:0 0 14px;color:#0E8741\">Portal support request</h2>"
        "<table style=\"font-size:14px;border-collapse:collapse\">"
        + row.format("Reason", esc(reason))
        + row.format("Customer", esc(name))
        + row.format("Email", esc(email or "—"))
        + row.format("Phone", esc(phone or "—"))
        + row.format("Vergent ID", esc(cid))
        + "</table>"
        "<p style=\"font-size:13px;color:#6b7280;margin:16px 0 6px\">Message</p>"
        "<div style=\"font-size:15px;line-height:1.55;white-space:pre-wrap;color:#111\">"
        + esc(message).replace("\n", "<br>") + "</div></div>"
    )
    text = ("Portal support request\n"
            f"Reason: {reason}\nCustomer: {name}\nEmail: {email or '-'}\n"
            f"Phone: {phone or '-'}\nVergent ID: {cid}\n\nMessage:\n{message}")
    send_kwargs = dict(to="info@cashinflash.com",
                       subject=f"Portal support: {reason} — {name}", html=html, text=text)
    if "@" in email:
        send_kwargs["reply_to"] = email
    ok, code, detail = resend_email.send(**send_kwargs)
    if not ok:
        log.warning("support email failed code=%s detail=%s", code, detail)
        return _json_response(502, {"error": "send_failed"})
    return _json_response(200, {"ok": True})


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    # Keep-warm ping (EventBridge schedule) — return immediately so the
    # container stays warm without touching Vergent.
    if isinstance(event, dict) and event.get("warmup"):
        return {"statusCode": 200, "body": "warm"}
    try:
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        path = http.get("path") or event.get("rawPath") or ""

        # Impersonation write-block: if an admin is viewing as a
        # customer (X-Impersonation-Token in headers) and the
        # method mutates state, return 403 before any handler
        # touches state. Reads pass through unchanged with
        # synthesized target-customer claims.
        from handlers import impersonation
        blocked = impersonation.maybe_block_write(
            event, impersonation.claims_with_impersonation(event))
        if blocked:
            return blocked

        if path.endswith("/presence/ping") and method == "POST":
            return record_presence(event)
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
        if path.endswith("/my-reapply/prefill") and method == "GET":
            return get_reapply_prefill(event)
        if path.endswith("/my-reapply/submit") and method == "POST":
            return submit_reapply(event)
        if path.endswith("/my-reapply/status") and method == "GET":
            return get_reapply_my_status(event)
        if path.endswith("/my-support") and method == "POST":
            return submit_support(event)
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
        if path.endswith("/my-esign/pending") and method == "GET":
            return get_pending_esign(event)
        if path.endswith("/my-esign/resend") and method == "POST":
            return resend_esign(event)
        if path.endswith("/my-esign/document") and method == "GET":
            return get_esign_document(event)
        if path.endswith("/my-esign/sign") and method == "POST":
            return submit_esign(event)
        if path.endswith("/plaid/link-token") and method == "POST":
            return plaid.link_token(event)
        if path.endswith("/plaid/exchange") and method == "POST":
            return plaid.exchange(event)
        if path.endswith("/plaid/connections") and method == "GET":
            return plaid.list_connections(event)
        # /api/plaid/connections/{itemId}
        if ("/plaid/connections/" in path
                and method == "DELETE"):
            parts = [p for p in path.split("/") if p]
            item_id = parts[-1] if parts else ""
            return plaid.disconnect(event, item_id)
        # Admin (cif-admin Cognito group) — list/detail
        if path.endswith("/admin/plaid/customers") and method == "GET":
            return plaid.list_admin_customers(event)
        if path.endswith("/admin/customers/search") and method == "GET":
            return search_admin_customers(event)
        # Admin impersonation (Phase 3) — mint short-lived tokens so
        # operators can "View as customer" into the portal frontend.
        if path.endswith("/admin/impersonate") and method == "POST":
            from handlers import impersonation
            return impersonation.mint_token(event)
        if path.endswith("/admin/end-impersonate") and method == "POST":
            from handlers import impersonation
            return impersonation.end_token(event)
        if ("/admin/plaid/customer/" in path
                and method == "GET"):
            parts = [p for p in path.split("/") if p]
            cid_param = parts[-1] if parts else ""
            return plaid.get_admin_customer(event, cid_param)
        # Admin (Phase U.3) — Plaid asset reports on demand
        if ("/admin/plaid/asset-report/" in path and method == "POST"):
            parts = [p for p in path.split("/") if p]
            item_id = parts[-1] if parts else ""
            return plaid.trigger_asset_report(event, item_id)
        if (path.endswith("/pdf") and "/admin/plaid/asset-report/" in path
                and method == "GET"):
            parts = [p for p in path.split("/") if p]
            # path = .../admin/plaid/asset-report/{token}/pdf
            tok = parts[-2] if len(parts) >= 2 else ""
            return plaid.get_asset_report_pdf(event, tok)
        if ("/admin/plaid/asset-report/" in path and method == "GET"):
            parts = [p for p in path.split("/") if p]
            tok = parts[-1] if parts else ""
            return plaid.get_asset_report(event, tok)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("loans handler unexpected error: %s", exc)
        return _json_response(200, {
            "error": "upstream_unavailable",
            "_detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            "_path": path,
        })
