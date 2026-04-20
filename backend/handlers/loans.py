"""
Customer Portal — Loans / Activity handler.

Routes (bound via SAM to the existing HttpApi with JWT authorizer):
  GET /api/my-loans/active    -> get_active_loan
  GET /api/my-loans/activity  -> get_activity  (?limit=5)

Auth model:
  The Cognito JWT authorizer runs first. We pull the signed-in user's
  Vergent customer id straight from the custom claim that Round 19A's
  PreSignUp trigger writes onto the Cognito ID token:

      event.requestContext.authorizer.jwt.claims["custom:vergentCustomerId"]

  With that id we call Vergent V2 directly using the shared API key from
  Secrets Manager. No AuthenticateCognito exchange needed — the key +
  customerId is sufficient for the CustomerPortal endpoints.

  If a specific Vergent endpoint returns 401/403 we still return a usable
  response (HTTP 200 with an empty/placeholder shape) so the dashboard
  renders the friendly empty state instead of crashing. The failure is
  logged for the next session to debug.

Environment:
  VERGENT_BASE_URL   e.g. https://prod.apim.vergentlms.com/external/shared
  VERGENT_SECRET_ARN Secrets Manager ARN holding {"xApiKey":"...", ...}

IAM (see infra/template.yaml):
  secretsmanager:GetSecretValue on VERGENT_SECRET_ARN only.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import boto3

# ─────────────────────────────────────────
# Setup
# ─────────────────────────────────────────
log = logging.getLogger()
log.setLevel(logging.INFO)

VERGENT_BASE_URL = os.environ["VERGENT_BASE_URL"].rstrip("/")
VERGENT_SECRET_ARN = os.environ["VERGENT_SECRET_ARN"]

_secrets = boto3.client("secretsmanager")
_api_key_cache: Optional[str] = None

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


def _customer_id(event: Dict[str, Any]) -> Optional[str]:
    c = _claims(event)
    # Some API Gateway versions flatten custom claims.
    cid = (
        c.get("custom:vergentCustomerId")
        or c.get("custom_vergentCustomerId")
        or c.get("vergentCustomerId")
    )
    if cid:
        return str(cid)
    return None


def _vergent_get(path: str, params: Dict[str, Any]) -> Tuple[int, Optional[Any]]:
    url = f"{VERGENT_BASE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{qs}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "x-api-key": _get_api_key(),
            "Accept": "application/json",
            "User-Agent": "cif-portal/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8") or "null"
            return status, json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.warning("Vergent %s -> %s: %s", path, e.code, body[:400])
        return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        log.error("Vergent %s network error: %s", path, e)
        return 0, None


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _shape_loan(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent's loan payload into the shape the dashboard expects."""
    return {
        "id": _pick(raw, "loanId", "LoanId", "id", "Id"),
        "status": _pick(raw, "status", "Status", "loanStatus", "LoanStatus") or "Current",
        "principal": _to_number(_pick(raw, "principal", "Principal", "originalAmount", "OriginalAmount", "amountFinanced", "AmountFinanced")),
        "balance": _to_number(_pick(raw, "currentBalance", "CurrentBalance", "balance", "Balance", "payoffAmount", "PayoffAmount")),
        "nextDueDate": _pick(raw, "nextPaymentDate", "NextPaymentDate", "nextDueDate", "NextDueDate"),
        "nextDueAmount": _to_number(_pick(raw, "nextPaymentAmount", "NextPaymentAmount", "nextDueAmount", "NextDueAmount")),
        "apr": _to_number(_pick(raw, "apr", "APR", "annualPercentageRate")),
        "termRemaining": _pick(raw, "termRemaining", "RemainingTerm", "paymentsRemaining"),
    }


def _to_number(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _active_filter(loan: Dict[str, Any]) -> bool:
    status = (loan.get("status") or "").lower()
    return any(token in status for token in ("active", "current", "past due", "grace", "open"))


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    cid = _customer_id(event)
    if not cid:
        log.warning("Missing custom:vergentCustomerId in JWT claims")
        return _json_response(200, {"loan": None, "reason": "no-customer-id"})

    # Primary: Customer Portal "Loans / Full" — returns all loans with detail.
    status, payload = _vergent_get("/api/CustomerPortal/Customer/Loans/Full", {"customerId": cid})

    loans: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        loans = payload
    elif isinstance(payload, dict):
        loans = payload.get("loans") or payload.get("Loans") or payload.get("items") or []
        if not loans and (payload.get("loanId") or payload.get("LoanId")):
            loans = [payload]

    if status >= 400 or not loans:
        # Fallback: a minimal "Loans" list endpoint some tenants expose.
        status2, payload2 = _vergent_get("/api/CustomerPortal/Customer/Loans", {"customerId": cid})
        if isinstance(payload2, list):
            loans = payload2
        elif isinstance(payload2, dict):
            loans = payload2.get("loans") or payload2.get("Loans") or payload2.get("items") or []

    shaped = [_shape_loan(l) for l in loans if isinstance(l, dict)]
    active = next((l for l in shaped if _active_filter(l)), None)

    if not active:
        return _json_response(200, {"loan": None})

    return _json_response(200, {"loan": active})


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
    cid = _customer_id(event)
    if not cid:
        return _json_response(200, {"items": []})

    qs = (event.get("queryStringParameters") or {}) or {}
    try:
        limit = max(1, min(int(qs.get("limit") or 5), 20))
    except (TypeError, ValueError):
        limit = 5

    status, payload = _vergent_get(
        "/api/CustomerPortal/Customer/Transactions",
        {"customerId": cid, "take": limit},
    )

    raw_items: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("transactions") or payload.get("Transactions") or payload.get("items") or []

    items = []
    for t in raw_items[:limit]:
        if not isinstance(t, dict):
            continue
        amount = _to_number(_pick(t, "amount", "Amount"))
        kind = (_pick(t, "type", "Type", "transactionType", "TransactionType") or "").lower()
        direction = "credit" if kind in ("payment", "credit", "refund") else "debit"
        items.append({
            "date": _pick(t, "date", "Date", "postedDate", "PostedDate", "transactionDate", "TransactionDate"),
            "description": _pick(t, "description", "Description", "memo", "Memo") or _pick(t, "type", "Type") or "Transaction",
            "amount": amount if amount is not None else 0,
            "direction": direction,
            "kind": kind or None,
        })

    return _json_response(200, {"items": items})


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
    except Exception as exc:  # last-ditch safety net — never 5xx the dashboard
        log.exception("loans handler unexpected error: %s", exc)
        return _json_response(200, {"loan": None, "items": [], "error": "upstream_unavailable"})
