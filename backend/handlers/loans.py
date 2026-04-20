"""
Customer Portal - Account + Loans handler.

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-profile       -> profile card data
  GET  /api/my-loans/active  -> active loan (returns null until Vergent routes v1)
  GET  /api/my-loans/activity -> recent activity (empty until v1 wired)
  POST /api/my-loan/new      -> returns handoff URL into Vergent loan-application UI

Auth model (the one that works today):
  - API Gateway Cognito JWT authorizer validates the ID token; claims land in
    event.requestContext.authorizer.jwt.claims.
  - We pull custom:vergentCustomerId from those claims (populated at signup
    by Round 19A's PreSignUp trigger).
  - Lambda authenticates as the SERVICE account against Vergent APIM once per
    container (camelCase body, x-api-key header) and caches the auth_token
    for ~1 hour.
  - Calls non-CustomerPortal v2 endpoints that accept the service token
    directly (status, handoff, RecoveryOptions). Customer-scoped v2 endpoints
    (/Customer/Profile, /Customer/Loans/Full) are blocked until Vergent
    enables AuthenticateCognito for our tenant.

Security: service credentials can read any customer at company 386. We
rely on the JWT authorizer to identify which customer this request is
about, then scope every Vergent call to that customer's id/email from
the JWT claims. Never trust customerId from request body/query.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

VERGENT_BASE_URL = os.environ.get(
    "VERGENT_BASE_URL", "https://prod.apim.vergentlms.com/external/shared"
).rstrip("/")
VERGENT_SECRET_ARN = os.environ["VERGENT_SECRET_ARN"]
HANDOFF_AUTHORITY = os.environ.get("VERGENT_HANDOFF_AUTHORITY", "cashinflash.apply.vergentlms.com")

_secrets = boto3.client("secretsmanager")
_creds_cache: Optional[Dict[str, str]] = None
_token_cache: Optional[str] = None
_token_exp: float = 0.0
TOKEN_TTL_SECS = 60 * 60  # refresh once an hour even though Vergent's Timeout is 24h

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


def _http(method: str, path: str, *, body: Optional[Dict[str, Any]] = None,
          headers: Optional[Dict[str, str]] = None, timeout: int = 10,
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
                try:
                    parsed = json.loads(raw)
                    # Vergent /api/authenticate returns a JSON-encoded-string
                    # body. Only double-decode when the inner string looks
                    # like more JSON (starts with { or [), otherwise keep the
                    # string as-is (e.g. PasswordReset/Search returns a GUID).
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
        log.warning("Vergent %s %s -> %s: %s", method, path, e.code, raw[:300])
        return e.code, None, raw
    except (urllib.error.URLError, TimeoutError) as exc:
        log.error("Vergent %s %s network error: %s", method, path, exc)
        return 0, None, ""


def _get_service_token() -> Optional[str]:
    """Service-account auth. Authenticates once per container hour."""
    global _token_cache, _token_exp
    if _token_cache and _token_exp > time.time():
        return _token_cache
    creds = _get_creds()
    status, body, _raw = _http(
        "POST",
        "/api/authenticate",
        body={"userName": creds["logonName"], "password": creds["password"]},
        headers={"x-api-key": creds["xApiKey"]},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("service authenticate failed status=%s", status)
        return None
    token = body.get("auth_token") or body.get("token") or body.get("Token")
    if not token:
        log.warning("service authenticate returned no token")
        return None
    _token_cache = token
    _token_exp = time.time() + TOKEN_TTL_SECS
    log.info("service auth cached for %ds", TOKEN_TTL_SECS)
    return token


def _authed_headers() -> Optional[Dict[str, str]]:
    """x-api-key + Bearer — the combination that works on v2 non-CustomerPortal endpoints."""
    tok = _get_service_token()
    if not tok:
        return None
    creds = _get_creds()
    return {"x-api-key": creds["xApiKey"], "Authorization": f"Bearer {tok}"}


def _mask_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = [c for c in raw if c.isdigit()]
    if len(digits) >= 4:
        return f"•••-•••-{''.join(digits[-4:])}"
    return raw


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_my_profile(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    email = (claims.get("email") or "").strip()

    # Profile base from Cognito claims (always available)
    profile = {
        "firstName": claims.get("given_name"),
        "lastName": claims.get("family_name"),
        "email": email,
        "emailVerified": claims.get("email_verified") in (True, "true"),
        "phone": claims.get("phone_number"),
        "phoneVerified": claims.get("phone_number_verified") in (True, "true"),
        "vergentCustomerId": cid,
        "status": None,
        "statusName": None,
        "vergentPhoneHint": None,
        "isTextMessagingEnabled": None,
        "isSecurityQuestionsSetup": None,
        "source": "cognito",
    }

    h = _authed_headers()
    if not h or not cid:
        return _json_response(200, profile)

    # Account status — always-accessible endpoint
    status_code, status_body, _ = _http("GET", f"/api/customer/{cid}/status", headers=h)
    if status_code == 200 and isinstance(status_body, dict):
        profile["status"] = status_body.get("status")
        profile["statusName"] = status_body.get("statusName")
        profile["source"] = "vergent"

    # RecoveryOptions — takes two calls (search → options) but gives us phone hint + text flag
    if email:
        s2, search_body, _ = _http("GET", f"/api/Customer/PasswordReset/Search/{urllib.parse.quote(email)}", headers=h)
        reset_token = None
        if s2 == 200:
            if isinstance(search_body, str):
                reset_token = search_body
            elif isinstance(search_body, dict):
                reset_token = search_body.get("token")
        if reset_token:
            s3, ro, _ = _http("GET", f"/api/Customer/PasswordReset/RecoveryOptions/{reset_token}", headers=h)
            if s3 == 200 and isinstance(ro, dict):
                profile["vergentPhoneHint"] = ro.get("phone")  # already masked by Vergent
                profile["isTextMessagingEnabled"] = ro.get("isTextMessagingEnabled")
                profile["isSecurityQuestionsSetup"] = ro.get("isSecurityQuestionsSetup")

    return _json_response(200, profile)


def request_new_loan_handoff(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(400, {"error": "no_customer_id"})

    h = _authed_headers()
    if not h:
        return _json_response(502, {"error": "vergent_unavailable"})

    status, body, _raw = _http(
        "POST",
        "/api/authenticate/handoff/create",
        body={
            "customerId": int(cid),
            "TargetRelativePage": "/",
            "ExpectedReferrerAuthority": HANDOFF_AUTHORITY,
        },
        headers=h,
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("handoff/create failed status=%s body=%s", status, str(body)[:200])
        return _json_response(502, {"error": "handoff_failed"})

    url = body.get("handoffUrl") or body.get("handoff_url")
    token = body.get("token")
    if not url:
        return _json_response(502, {"error": "handoff_no_url"})
    return _json_response(200, {"url": url, "token": token})


def get_active_loan(event: Dict[str, Any]) -> Dict[str, Any]:
    # Until Vergent enables the v1 routes (or AuthenticateCognito), we can't
    # enumerate a customer's loans. Return a clean empty state so the UI
    # renders "No active loan right now" with the Apply CTA.
    return _json_response(200, {"loan": None, "reason": "pending_vergent_route"})


def get_activity(event: Dict[str, Any]) -> Dict[str, Any]:
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
