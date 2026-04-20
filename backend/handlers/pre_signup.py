"""Cognito Pre-Sign-Up trigger.

Guards we enforce on every SignUp attempt before Cognito creates the user:

  1. DUPLICATE_EMAIL           — email already in the pool
  2. DUPLICATE_VERGENT_CUSTOMER — another Cognito user already owns this
                                  custom:vergentCustomerId
  3. MISSING_VERGENT_EMAIL     — Vergent has no email on file for the
                                  claimed customer (we can't decide what
                                  email to lock them to)
  4. EMAIL_MISMATCH            — the signup email differs from Vergent's
                                  on-file email for that customer
  5. VERGENT_UNAVAILABLE       — Vergent lookup failed; fail closed (safer
                                  than allowing a mismatched account)

Errors surface to the SPA as UserLambdaValidationException with the code
in the message. signup.html's humanizeError() keys off each code.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

_cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_secrets = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))

V1_BASE = os.environ.get("VERGENT_V1_BASE_URL", "https://shared.vergentlms.com/api/api").rstrip("/")
VERGENT_SECRET_ARN = os.environ.get("VERGENT_SECRET_ARN", "")

# Warm-container caches — avoid re-authenticating to Vergent on every invocation.
_creds_cache: Optional[dict] = None
_v1_token: Optional[str] = None
_v1_token_exp: float = 0.0
TOKEN_TTL = 60 * 60


# ─────────────────────────────────────────
# Main handler
# ─────────────────────────────────────────
def lambda_handler(event, context):
    # Cognito passes the pool id on every invocation.
    pool_id = event.get("userPoolId", "")
    attrs   = event.get("request", {}).get("userAttributes", {}) or {}
    vcid    = (attrs.get("custom:vergentCustomerId") or "").strip()
    email   = (attrs.get("email") or "").strip().lower()
    incoming_sub = event.get("userName", "")

    # 1. Email uniqueness (Cognito-native filter).
    if email and _exists_by_email(pool_id, email, exclude_sub=incoming_sub):
        raise Exception("DUPLICATE_EMAIL")

    # 2. vergentCustomerId uniqueness (paginated scan).
    if vcid and _exists_by_vergent_id(pool_id, vcid, exclude_sub=incoming_sub):
        raise Exception("DUPLICATE_VERGENT_CUSTOMER")

    # 3/4/5. Vergent email-match check.
    # Skip only when VERGENT_SECRET_ARN is not yet configured (safety net for
    # local testing); in prod this env var is always set.
    if vcid and VERGENT_SECRET_ARN:
        vergent_email = _fetch_vergent_email(vcid)
        if vergent_email is None:
            # We could not reach Vergent or got an unexpected response.
            raise Exception("VERGENT_UNAVAILABLE")
        if not vergent_email:
            # Customer exists in Vergent but has no email on file.
            raise Exception("MISSING_VERGENT_EMAIL")
        if vergent_email.strip().lower() != email:
            log.info("email mismatch: signup=%s vergent=%s cust=%s",
                     _mask(email), _mask(vergent_email), vcid)
            raise Exception("EMAIL_MISMATCH")

    # All guards passed — user stays UNCONFIRMED until they enter the
    # verification code Cognito will send.
    return event


# ─────────────────────────────────────────
# Cognito helpers
# ─────────────────────────────────────────
def _exists_by_email(pool_id: str, email: str, *, exclude_sub: str = "") -> bool:
    """Fast path — Cognito natively supports filtering on email."""
    if not pool_id:
        return False
    try:
        resp = _cognito.list_users(
            UserPoolId=pool_id,
            Filter=f'email = "{email}"',
            Limit=3,
        )
    except ClientError:
        return False
    for u in resp.get("Users", []):
        if u.get("Username") != exclude_sub:
            return True
    return False


def _exists_by_vergent_id(pool_id: str, vcid: str, *, exclude_sub: str = "") -> bool:
    """Slow path — custom attributes aren't filterable. Scan ≤ 5000 users.
    Move to a DynamoDB index (populated by a PostConfirmation trigger) when
    the pool outgrows that.
    """
    if not pool_id:
        return False
    pagination_token = None
    scanned = 0
    MAX_SCAN = 5000
    while scanned < MAX_SCAN:
        kwargs = {"UserPoolId": pool_id, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = _cognito.list_users(**kwargs)
        except ClientError:
            return False
        for u in resp.get("Users", []):
            if u.get("Username") == exclude_sub:
                continue
            for a in u.get("Attributes", []):
                if a.get("Name") == "custom:vergentCustomerId" and a.get("Value") == vcid:
                    return True
        scanned += len(resp.get("Users", []))
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    return False


# ─────────────────────────────────────────
# Vergent helpers (mirrors loans.py pattern)
# ─────────────────────────────────────────
def _get_creds() -> Optional[dict]:
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    try:
        resp = _secrets.get_secret_value(SecretId=VERGENT_SECRET_ARN)
    except ClientError as e:
        log.warning("secret read failed: %s", e.response.get("Error", {}).get("Code"))
        return None
    payload = json.loads(resp["SecretString"])
    _creds_cache = {
        "logonName": payload.get("logonName"),
        "password":  payload.get("password"),
    }
    if not _creds_cache["logonName"] or not _creds_cache["password"]:
        log.warning("vergent creds incomplete in secret")
        return None
    return _creds_cache


def _http(url: str, method: str = "GET", body=None, headers=None, timeout: int = 8) -> Tuple[int, object, str]:
    h = {"Accept": "application/json", "User-Agent": "cif-presignup/1.0"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace") or ""
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, str) and parsed.strip()[:1] in ("{", "["):
                        parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    parsed = None
            return r.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        log.warning("vergent %s %s -> %s: %s", method, url, e.code, raw[:200])
        return e.code, None, raw
    except Exception as e:
        log.error("vergent %s %s network: %s", method, url, e)
        return 0, None, ""


def _get_v1_token() -> Optional[str]:
    global _v1_token, _v1_token_exp
    if _v1_token and _v1_token_exp > time.time():
        return _v1_token
    creds = _get_creds()
    if not creds:
        return None
    status, body, _raw = _http(
        f"{V1_BASE}/authenticate", "POST",
        body={"LogonName": creds["logonName"], "Password": creds["password"]},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    tok = body.get("Token")
    if tok:
        _v1_token = tok
        _v1_token_exp = time.time() + TOKEN_TTL
    return tok


def _fetch_vergent_email(customer_id: str) -> Optional[str]:
    """Returns:
        "foo@bar.com"   — Vergent has this email on file
        ""              — Vergent recognizes the customer but the email field is blank
        None            — we couldn't reach Vergent (caller should treat as VERGENT_UNAVAILABLE)
    """
    tok = _get_v1_token()
    if not tok:
        return None
    status, body, _raw = _http(
        f"{V1_BASE}/V1/GetCustomer/{customer_id}", "GET",
        headers={"Token": tok},
    )
    if status in (401, 403):
        # Token might have rotated — force a refresh and retry once.
        global _v1_token_exp
        _v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, body, _raw = _http(
                f"{V1_BASE}/V1/GetCustomer/{customer_id}", "GET",
                headers={"Token": tok2},
            )
    if status != 200 or not isinstance(body, dict):
        return None
    # Vergent returns "EmailAddr" on GetCustomer (see GetCustomerData for
    # the cust-nested variant).
    return (body.get("EmailAddr") or "").strip()


def _mask(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    name, _, dom = email.partition("@")
    return f"{name[:2]}***@{dom}" if len(name) > 2 else f"{name[:1]}***@{dom}"
