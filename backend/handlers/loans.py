"""
Customer Portal - Loans / Activity handler.

Routes (bound to the existing HttpApi with Cognito JWT authorizer):
  GET /api/my-loans/active     -> get_active_loan
  GET /api/my-loans/activity   -> get_activity  (?limit=5)

Vergent v2 auth model:
  1. Cognito JWT authorizer validates the ID token at the gateway; claims
     land in event.requestContext.authorizer.jwt.claims. The RAW id token
     is in event.headers.authorization (lower-cased by HTTP API v2).
  2. We exchange that id token at
        POST /api/CustomerPortal/AuthenticateCognito  body={"jwt": "..."}
     to receive a Customer Portal bearer token.
  3. Subsequent customer-scoped calls use both headers:
        Authorization: Bearer <cp_token>
        x-api-key: <shared-machine-key from Secrets Manager>

  The CP token is cached in-process keyed by the Cognito `sub` for the
  lifetime of a warm Lambda container (~5 minutes, bounded by our own
  TTL since the token's own exp is not surfaced in the response).

Environment:
  VERGENT_BASE_URL    https://prod.apim.vergentlms.com/external/shared
  VERGENT_SECRET_ARN  Secrets Manager ARN holding {"xApiKey":"..."}
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

VERGENT_BASE_URL = os.environ["VERGENT_BASE_URL"].rstrip("/")
VERGENT_SECRET_ARN = os.environ["VERGENT_SECRET_ARN"]

_secrets = boto3.client("secretsmanager")
_api_key_cache: Optional[str] = None
_cp_token_cache: Dict[str, Tuple[str, float]] = {}  # sub -> (token, expiresAt)
CP_TOKEN_TTL_SECS = 5 * 60

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Cache-Control": "no-store",
}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def _get_api_key() -> str:
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    resp = _secrets.get_secret_value(SecretId=VERGENT_SECRET_ARN)
    payload = json.loads(resp["SecretString"])
    key = payload.get("xApiKey") or payload.get("x-api-key") or payload.get("apiKey")
    if not key:
        raise RuntimeError("Vergent secret missing xApiKey")
    _api_key_cache = key
    return key


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


def _raw_id_token(event: Dict[str, Any]) -> Optional[str]:
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    return None


def _vergent_request(
    method: str,
    path: str,
    *,
    cp_token: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Tuple[int, Optional[Any], str]:
    """Returns (status, parsed_body_or_None, raw_text_body_for_logging)."""
    url = f"{VERGENT_BASE_URL}{path}"
    if query:
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        if qs:
            url = f"{url}?{qs}"

    headers = {
        "x-api-key": _get_api_key(),
        "Accept": "application/json",
        "User-Agent": "cif-portal/1.0",
    }
    if cp_token:
        headers["Authorization"] = f"Bearer {cp_token}"

    data: Optional[bytes] = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or ""
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        log.warning("Vergent %s %s -> %s: %s", method, path, e.code, raw[:400])
        return e.code, None, raw
    except (urllib.error.URLError, TimeoutError) as e:
        log.error("Vergent %s %s network error: %s", method, path, e)
        return 0, None, ""


def _authenticate_cognito(id_token: str, sub: str) -> Optional[str]:
    """Exchange a Cognito id token for a Customer Portal bearer token."""
    cached = _cp_token_cache.get(sub)
    if cached and cached[1] > time.time():
        return cached[0]

    status, body, _raw = _vergent_request(
        "POST",
        "/api/CustomerPortal/AuthenticateCognito",
        body={"jwt": id_token},
        timeout=10,
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("AuthenticateCognito failed (status=%s)", status)
        return None

    if body.get("isAccountLocked"):
        log.warning("Customer account is locked per AuthenticateCognito response")
    token = body.get("token")
    if not token:
        log.warning("AuthenticateCognito returned no token: keys=%s", list(body.keys()))
        return None

    _cp_token_cache[sub] = (token, time.time() + CP_TOKEN_TTL_SECS)
    log.info("AuthenticateCognito ok for sub=%s", sub[:8])
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


def _shape_loan_card(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent LoanCardModel → dashboard shape."""
    principal = _to_number(_pick(raw, "originalPrincipal", "principalBalance"))
    balance = _to_number(_pick(raw, "payoffAmount", "currentBalance", "originalBalance"))
    return {
        "id": _pick(raw, "loanHeaderId", "publicLoanId"),
        "loanHeaderId": _pick(raw, "loanHeaderId"),
        "publicLoanId": _pick(raw, "publicLoanId"),
        "status": _pick(raw, "loanStatus") or "Current",
        "loanClass": _pick(raw, "loanClassTypeAbbrev"),
        "principal": principal,
        "balance": balance,
        "payoffAmount": _to_number(_pick(raw, "payoffAmount")),
        "amountDue": _to_number(_pick(raw, "amountDue")),
        "nextDueDate": _pick(raw, "nextPaymentDate", "nextPaymentScheduleDate"),
        "nextDueAmount": _to_number(_pick(raw, "nextPaymentScheduleAmount", "amountDue")),
        "apr": _to_number(_pick(raw, "originalFeeApr")),
        "originationDate": _pick(raw, "loanDate", "originationDate"),
        "availableCash": _to_number(_pick(raw, "availableCash")),
        "availableCredit": _to_number(_pick(raw, "availableCredit")),
        "isACHOrCardPaymentScheduled": bool(_pick(raw, "isACHOrCardPaymentScheduled") or False),
        "paymentScheduleSource": _pick(raw, "paymentScheduleSource"),
    }


def _shape_transaction(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LoanTransactionHistoryModel → dashboard activity row."""
    total = _to_number(_pick(raw, "total", "change", "principal"))
    type_name = (_pick(raw, "typeName") or "").strip()
    # Payments / adjustments reduce balance (credit to customer); fees / disbursements are debits.
    lowered = type_name.lower()
    if any(k in lowered for k in ("payment", "refund", "credit")):
        direction = "credit"
    elif any(k in lowered for k in ("fee", "disbursement", "draw", "charge")):
        direction = "debit"
    else:
        # Fallback on sign of the change field.
        change = _to_number(_pick(raw, "change"))
        direction = "credit" if (change is not None and change < 0) else "debit"
    return {
        "id": _pick(raw, "transactionItemId"),
        "date": _pick(raw, "businessDate"),
        "description": type_name or "Transaction",
        "amount": abs(total) if total is not None else 0,
        "direction": direction,
        "balance": _to_number(_pick(raw, "balance")),
        "cardLast4": _pick(raw, "creditCardLast4"),
    }


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    sub = claims.get("sub") or ""
    id_token = _raw_id_token(event)
    if not id_token or not sub:
        log.warning("Missing id token or sub")
        return _json_response(200, {"loan": None, "reason": "no-id-token"})

    cp_token = _authenticate_cognito(id_token, sub)
    if not cp_token:
        return _json_response(200, {"loan": None, "reason": "auth-exchange-failed"})

    # /api/CustomerPortal/Loans returns LoanInfoModel: {loanCards: [LoanCardModel]}
    # Description: "Gets the open loans for the current user" — already filtered.
    status, payload, _raw = _vergent_request(
        "GET",
        "/api/CustomerPortal/Loans",
        cp_token=cp_token,
    )
    if status != 200 or not isinstance(payload, dict):
        log.warning("Loans call failed status=%s", status)
        return _json_response(200, {"loan": None, "reason": "loans-upstream-error"})

    cards = payload.get("loanCards") or []
    if not isinstance(cards, list) or not cards:
        return _json_response(200, {"loan": None})

    # Pick the most recent / first open loan. Vergent returns open loans here.
    shaped = [_shape_loan_card(c) for c in cards if isinstance(c, dict)]
    active = shaped[0] if shaped else None

    return _json_response(200, {"loan": active, "loanCount": len(shaped)})


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    sub = claims.get("sub") or ""
    id_token = _raw_id_token(event)
    if not id_token or not sub:
        return _json_response(200, {"items": []})

    cp_token = _authenticate_cognito(id_token, sub)
    if not cp_token:
        return _json_response(200, {"items": [], "reason": "auth-exchange-failed"})

    qs = (event.get("queryStringParameters") or {}) or {}
    try:
        limit = max(1, min(int(qs.get("limit") or 5), 20))
    except (TypeError, ValueError):
        limit = 5

    # Find the active loan first (transactions are loan-scoped in v2).
    status, payload, _raw = _vergent_request(
        "GET", "/api/CustomerPortal/Loans", cp_token=cp_token
    )
    if status != 200 or not isinstance(payload, dict):
        return _json_response(200, {"items": []})
    cards = payload.get("loanCards") or []
    if not cards:
        return _json_response(200, {"items": []})
    loan_id = _pick(cards[0], "loanHeaderId")
    if loan_id is None:
        return _json_response(200, {"items": []})

    status2, txn_payload, _raw2 = _vergent_request(
        "GET",
        f"/api/CustomerPortal/Loans/{loan_id}/Transactions",
        cp_token=cp_token,
    )
    if status2 != 200 or not isinstance(txn_payload, dict):
        return _json_response(200, {"items": []})

    history = txn_payload.get("loanTransactionHistoryList") or []
    rows = [_shape_transaction(t) for t in history if isinstance(t, dict)]
    rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)

    return _json_response(200, {"items": rows[:limit], "loanHeaderId": loan_id})


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
    except Exception as exc:  # never 5xx the dashboard
        log.exception("loans handler unexpected error: %s", exc)
        return _json_response(200, {"loan": None, "items": [], "error": "upstream_unavailable"})
