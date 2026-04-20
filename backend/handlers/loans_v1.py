"""
Customer Portal - Loans / Activity handler (Vergent v1 LMS API edition).

This is a *drop-in replacement* for loans.py that uses the v1 LMS API at
`prod.api.vergentlms.com` instead of the v2 Customer Portal API at the
APIM gateway. v1 takes customerId in the URL path and only needs a
service-account Token, so we don't need Vergent's AuthenticateCognito
flow (which is unblocked on their side).

Activation plan:
  1. Add fields to Secrets Manager `cif-portal/vergent/credentials`:
        "v1LogonName": "CifPortalV1",
        "v1Password":  "<from Vergent>"
  2. Update the Lambda handler to point at this module:
        aws lambda update-function-configuration \
          --function-name cif-portal-loans-dev \
          --handler handlers.loans_v1.lambda_handler \
          --environment 'Variables={
              VERGENT_V1_BASE_URL=https://prod.api.vergentlms.com,
              VERGENT_SECRET_ARN=arn:...:secret:cif-portal/vergent/credentials-3pJJ1M
          }'
  3. Redeploy: update-function-code with this zip. No route changes needed.
  4. Hard-refresh the dashboard — real loan data appears.

Routes (unchanged, bound to the existing HttpApi with Cognito JWT authorizer):
  GET /api/my-loans/active    -> get_active_loan
  GET /api/my-loans/activity  -> get_activity  (?limit=5)

Auth model:
  - API Gateway's Cognito JWT authorizer validates the customer's ID token
    and puts the claims on event.requestContext.authorizer.jwt.claims.
  - We extract `custom:vergentCustomerId` from the claims. Round 19A's
    PreSignUp trigger writes it during signup so every portal customer has it.
  - Lambda logs in as the SERVICE account (CifPortalV1) to Vergent v1 ONCE
    per container, caches the `Token` header value for ~1h, and uses it on
    every call for any customer. The customer's own identity stays in the
    URL path (/api/V1/{cid}/loans/all).
  - Security note: service credentials have broad read access to all
    customers under company 386. The customer-scope is enforced by OUR
    Lambda trusting the Cognito JWT claim — a misconfigured Cognito
    authorizer would let customer A fetch customer B's data. Keep the
    JWT authorizer in place and never expose this Lambda without auth.

Failure modes:
  - Vergent 401/500 on auth → loan: null, reason: "auth-failed"
  - Vergent 404 on loans  → loan: null (clean empty state)
  - Missing customerId in JWT → loan: null, reason: "no-customer-id"
  - Never 5xx the dashboard. Top-level catch converts unexpected
    exceptions into 200 {loan:null, items:[], error:"upstream_unavailable"}.
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

VERGENT_BASE_URL = os.environ.get(
    "VERGENT_V1_BASE_URL", "https://prod.api.vergentlms.com"
).rstrip("/")
VERGENT_SECRET_ARN = os.environ["VERGENT_SECRET_ARN"]

_secrets = boto3.client("secretsmanager")
_creds_cache: Optional[Dict[str, str]] = None

# Service-account token cache. Vergent's Timeout response field is 86400s
# (24h) but we refresh after 1h to stay safely within the window.
_token: Optional[str] = None
_token_exp: float = 0.0
TOKEN_TTL_SECS = 60 * 60

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
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
    logon = payload.get("v1LogonName") or payload.get("logonName")
    password = payload.get("v1Password") or payload.get("password")
    if not logon or not password:
        raise RuntimeError("v1LogonName / v1Password missing from secret")
    _creds_cache = {"logonName": logon, "password": password}
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


def _customer_id(event: Dict[str, Any]) -> Optional[str]:
    c = _claims(event)
    cid = (
        c.get("custom:vergentCustomerId")
        or c.get("custom_vergentCustomerId")
        or c.get("vergentCustomerId")
    )
    return str(cid) if cid else None


def _http(method: str, path: str, *, body: Optional[Dict[str, Any]] = None,
          headers: Optional[Dict[str, str]] = None, timeout: int = 15,
          query: Optional[Dict[str, Any]] = None) -> Tuple[int, Optional[Any], str]:
    url = f"{VERGENT_BASE_URL}{path}"
    if query:
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        if qs:
            url = f"{url}?{qs}"
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
                # Vergent's /api/authenticate double-encodes its JSON response.
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, str):
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
        log.warning("Vergent %s %s -> %s: %s", method, path, e.code, raw[:400])
        return e.code, None, raw
    except (urllib.error.URLError, TimeoutError) as exc:
        log.error("Vergent %s %s network error: %s", method, path, exc)
        return 0, None, ""


def _get_service_token() -> Optional[str]:
    global _token, _token_exp
    if _token and _token_exp > time.time():
        return _token
    creds = _get_creds()
    status, body, _raw = _http(
        "POST",
        "/api/authenticate",
        body={"LogonName": creds["logonName"], "Password": creds["password"]},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("v1 authenticate failed status=%s", status)
        return None
    token = body.get("Token") or body.get("token") or body.get("auth_token")
    if not token:
        log.warning("authenticate returned no token; keys=%s", list(body.keys()))
        return None
    _token = token
    _token_exp = time.time() + TOKEN_TTL_SECS
    log.info("v1 service token cached for %ds", TOKEN_TTL_SECS)
    return token


def _pick(d: Dict[str, Any], *keys: str) -> Any:
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


def _shape_loan(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize v1 LoanHeader → the dashboard shape."""
    # v1 /api/V1/{customerId}/loans/all returns [{LoanHeader: {...}, ...other sections}]
    hdr = raw.get("LoanHeader") if isinstance(raw.get("LoanHeader"), dict) else raw
    return {
        "id": _pick(hdr, "HdrId", "LoanHeaderId", "TransHdrId", "LoanId", "Id"),
        "status": _pick(hdr, "LoanStatus", "Status", "SubStatus") or "Current",
        "loanClass": _pick(hdr, "LoanClassAbbrev", "LoanClass", "LoanType"),
        "principal": _to_number(_pick(hdr, "OriginalPrincipal", "Principal",
                                      "PrincipalBalance", "OriginalAmount")),
        "balance": _to_number(_pick(hdr, "PayoffAmount", "CurrentBalance",
                                    "Balance", "Payoff")),
        "payoffAmount": _to_number(_pick(hdr, "PayoffAmount")),
        "amountDue": _to_number(_pick(hdr, "AmountDue", "MinAmountDue")),
        "nextDueDate": _pick(hdr, "NextPaymentDate", "NextDueDate"),
        "nextDueAmount": _to_number(_pick(hdr, "NextPaymentAmount", "MinAmountDue",
                                          "PrinPerPayment", "AmountDue")),
        "apr": _to_number(_pick(hdr, "Apr", "APR", "OriginalFeeApr")),
        "originationDate": _pick(hdr, "OriginationDate", "LoanDate"),
        "isEligibleForRefi": bool(_pick(hdr, "IsEligibleForRefi") or False),
    }


def _is_active(loan: Dict[str, Any]) -> bool:
    status = (loan.get("status") or "").lower()
    if any(tok in status for tok in ("paid", "closed", "written off", "charged off")):
        return False
    # If neither balance nor amountDue are set, treat as active (open loan often has 0 due)
    balance = loan.get("balance")
    due = loan.get("amountDue")
    if balance is None and due is None:
        return True
    return (balance is not None and balance > 0) or (due is not None and due > 0)


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    cid = _customer_id(event)
    if not cid:
        log.warning("Missing custom:vergentCustomerId")
        return _json_response(200, {"loan": None, "reason": "no-customer-id"})

    token = _get_service_token()
    if not token:
        return _json_response(200, {"loan": None, "reason": "auth-failed"})

    status, payload, _raw = _http(
        "GET",
        f"/api/V1/{cid}/loans/all",
        headers={"Token": token},
    )
    if status in (401, 403):
        # Token might have expired unexpectedly; force-refresh once.
        global _token_exp
        _token_exp = 0
        token2 = _get_service_token()
        if token2:
            status, payload, _raw = _http(
                "GET", f"/api/V1/{cid}/loans/all", headers={"Token": token2}
            )

    if status != 200 or not isinstance(payload, list):
        log.warning("loans/all non-200 status=%s", status)
        return _json_response(200, {"loan": None, "reason": "loans-upstream-error"})

    shaped = [_shape_loan(l) for l in payload if isinstance(l, dict)]
    active = next((l for l in shaped if _is_active(l)), None)
    return _json_response(200, {"loan": active, "loanCount": len(shaped)})


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
    """v1 transaction history requires (custId, HdrId, companyId, storeId, userId)
    on `/api/V1/GetCustomerLoanHistory`. Wiring that out once we have a real
    response to inspect; for now return an empty list so the UI renders
    the "no activity yet" empty state cleanly."""
    cid = _customer_id(event)
    if not cid:
        return _json_response(200, {"items": []})
    return _json_response(200, {"items": []})


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
        if path.endswith("/my-loans/active"):
            return get_active_loan(event)
        if path.endswith("/my-loans/activity"):
            return get_activity(event)
        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("loans_v1 unexpected error: %s", exc)
        return _json_response(200, {"loan": None, "items": [], "error": "upstream_unavailable"})
