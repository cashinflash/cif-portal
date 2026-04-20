"""
Customer Portal - Account + Loans handler (Vergent v1 LMS API).

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-profile       -> profile card data
  GET  /api/my-loans/active  -> active loan with balance / due date / status
  GET  /api/my-loans/activity -> recent activity (empty until loan/transactions wired)
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
_creds_cache: Optional[Dict[str, str]] = None

# v1 service Token (GUID) — used on every v1 LMS call.
_v1_token: Optional[str] = None
_v1_token_exp: float = 0.0

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
    global _v1_token, _v1_token_exp
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
    log.info("v1 service Token cached (%ds)", TOKEN_TTL_SECS)
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
    return {
        "id": hdr.get("hdr_id"),
        "publicId": detail.get("PublicLoanId") or hdr.get("PublicLoanId"),
        "loanClass": hdr.get("LoanModelName") or hdr.get("LoanTypeName", "").split(".")[-1] or None,
        "status": "Current" if is_outstanding else (hdr.get("SubStatus") or "Closed"),
        "statusId": status_id,
        "isOutstanding": is_outstanding,
        "principal": loan_amount,
        "balance": payoff if payoff is not None else amount_due,
        "payoffAmount": payoff,
        "amountDue": amount_due,
        "minAmountDue": min_due,
        "nextDueDate": _format_iso(hdr.get("DueDate") or hdr.get("NextPaymentDate")),
        "nextDueAmount": min_due if min_due is not None else amount_due,
        "originationDate": _format_iso(hdr.get("OriginationDate")),
        "storeId": hdr.get("StoreId"),
        "storeName": detail.get("StoreName") or hdr.get("StoreName"),
        "daysLate": detail.get("DaysLate"),
        "isEligibleForRefi": bool(hdr.get("IsEligibleForRefi") or False),
        "isInRescindPeriod": bool(hdr.get("IsInRescindPeriod") or False),
    }


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
        if isinstance(phones, list):
            primary_phone = next(
                (p for p in phones if isinstance(p, dict) and p.get("IsPrimary")),
                phones[0] if phones and isinstance(phones[0], dict) else None,
            )
            if primary_phone:
                profile["vergentPhoneHint"] = _mask_phone(primary_phone.get("number"))

    return _json_response(200, profile)


def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None, "reason": "no-customer-id"})

    status, body = _v1_get(f"/V1/{cid}/loans")
    if status != 200 or not isinstance(body, list):
        log.warning("v1 loans call failed status=%s", status)
        return _json_response(200, {"loan": None, "reason": "upstream-error"})

    shaped = [_shape_v1_loan(item) for item in body if isinstance(item, dict)]
    # Pick the first outstanding loan; fall back to most recent by origination date.
    outstanding = [l for l in shaped if l.get("isOutstanding")]
    active = outstanding[0] if outstanding else (shaped[0] if shaped else None)
    return _json_response(200, {"loan": active, "loanCount": len(shaped), "allLoans": shaped})


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
    # v1 transaction history at /api/api/V1/GetCustomerLoanHistory requires
    # (custId, HdrId, companyId, storeId, userId) — wireable once we pull the
    # active loan. Holding off on this until we confirm the endpoint's real
    # response shape against the live call.
    return _json_response(200, {"items": []})


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

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("loans handler unexpected error: %s", exc)
        return _json_response(200, {"error": "upstream_unavailable"})
