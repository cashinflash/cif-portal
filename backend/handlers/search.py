"""POST /api/search — Vergent customer lookup (pre-login, unauthenticated).

Step 1: POST /api/CustomerPortal/Customer/Search at the APIM gateway,
narrowed client-side by first + last name (defense in depth on top of
Vergent's server-side SSN + DOB match).

Step 2 (NEW): the v2 search result doesn't include the customer's email.
We follow up with GET /api/api/V1/GetCustomer/{id} at
shared.vergentlms.com to pull the email (field name `EmailAddr`), so
signup.html can lock the email input to what Vergent has on file.

Returns:
  { match: "single", vergentCustomerId, email, firstName, lastName, hasPortalAccount }
  { match: "none" }
  { match: "multiple" }
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
import boto3
from botocore.exceptions import ClientError

import aws_secrets
import vergent
from responses import ok, error, parse_body

_log = logging.getLogger()
_log.setLevel(logging.INFO)


_cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")

V1_BASE = os.environ.get("VERGENT_V1_BASE_URL", "https://shared.vergentlms.com/api/api").rstrip("/")
VERGENT_CREDS_SECRET = os.environ.get("VERGENT_CREDS_SECRET", "cif-portal/vergent/credentials")

# Warm-container v1 service-token cache (avoids re-authing on every /search call).
_v1_token = None
_v1_token_exp = 0.0
_V1_TOKEN_TTL = 60 * 60


def lambda_handler(event, context):
    # Top-level safety net — any uncaught exception below returns a
    # structured 500 so the customer sees a useful message instead of
    # the API Gateway-native "Internal Server Error".
    try:
        return _handle_search(event, context)
    except Exception as exc:
        _log.exception("search handler unhandled exception: %s", exc)
        return error(
            "We couldn't look up your account right now. Please try again or call (747) 270-7121.",
            status=500,
            code="internal_error",
        )


def _handle_search(event, context):
    body = parse_body(event)
    required = ["firstName", "lastName", "dob", "idNumber"]
    missing = [k for k in required if not body.get(k)]
    if missing:
        return error(f"Missing fields: {', '.join(missing)}", status=400)

    phone_digits = "".join(c for c in (body.get("phone") or "") if c.isdigit())
    # SSN: strip dashes and spaces. Both '123-45-6789' and '123456789'
    # arrive at Vergent the same way.
    id_digits = "".join(c for c in body["idNumber"] if c.isdigit())
    birth_date_iso = _to_iso_datetime(body["dob"])  # YYYY-MM-DD -> full ISO

    try:
        # userType=1 is consumer (verified by probe 2026-04-18).
        # userType=0 and userType=2 both trigger "Bussiness name" validation.
        matches = vergent.customer_search(
            first_name=body["firstName"].strip(),
            last_name=body["lastName"].strip(),
            birth_date_iso=birth_date_iso,
            phone_number=phone_digits,
            id_number=id_digits,
            user_type=1,
        )
    except Exception as e:
        return error(f"Vergent lookup failed: {e}", status=502)

    first = body["firstName"].strip().lower()
    last = body["lastName"].strip().lower()
    verified = [m for m in matches if _name_matches(m, first, last)]

    if not verified:
        return ok({"match": "none"})
    if len(verified) > 1:
        return ok({"match": "multiple"})

    customer = verified[0]
    vergent_customer_id = str(customer.get("customerId") or "")
    # v2 Search does NOT return email — always pull from v1 GetCustomer.
    # Falls back to the v2 field if the v1 call fails (unlikely).
    email = _fetch_v1_email(vergent_customer_id) or (customer.get("email") or "")
    first_name = customer.get("firstName") or body["firstName"]
    last_name = customer.get("lastName") or body["lastName"]

    # Cognito user-exists check is best-effort. If Cognito throws an
    # unexpected exception (throttle, region outage, unknown boto3
    # shape), degrade to hasPortalAccount=false so the customer can
    # still proceed to the code-send step instead of hitting a 500.
    try:
        has_portal_account = _cognito_user_exists(email, vergent_customer_id)
    except Exception as cog_exc:
        _log.exception("cognito_user_exists failed cid=%s: %s",
                       vergent_customer_id, cog_exc)
        has_portal_account = False

    return ok({
        "match": "single",
        "vergentCustomerId": vergent_customer_id,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "hasPortalAccount": has_portal_account,
    })


# ─────────────────────────────────────────
# v1 LMS helpers (only used on a single-match result)
# ─────────────────────────────────────────
def _v1_http(path, method="GET", body=None, headers=None, timeout=8):
    url = f"{V1_BASE}{path}"
    h = {"Accept": "application/json", "User-Agent": "cif-portal/1.0"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw) if raw else None
                if isinstance(parsed, str) and parsed.strip()[:1] in ("{", "["):
                    parsed = json.loads(parsed)
                return r.status, parsed
            except json.JSONDecodeError:
                return r.status, None
    except urllib.error.HTTPError as e:
        try:
            raw = (e.read() or b"").decode("utf-8", "replace")
        except Exception:
            raw = ""
        _log.warning("v1 %s %s -> %s: %s", method, path, e.code, raw[:200])
        return e.code, None
    except Exception as e:
        _log.error("v1 %s %s network: %s", method, path, e)
        return 0, None


def _get_v1_token():
    global _v1_token, _v1_token_exp
    if _v1_token and _v1_token_exp > time.time():
        return _v1_token
    try:
        creds = aws_secrets.load(VERGENT_CREDS_SECRET)
    except Exception as e:
        _log.warning("v1 secret load failed: %s", e)
        return None
    status, body = _v1_http(
        "/authenticate", "POST",
        body={"LogonName": creds.get("logonName"), "Password": creds.get("password")},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    tok = body.get("Token")
    if tok:
        _v1_token = tok
        _v1_token_exp = time.time() + _V1_TOKEN_TTL
    return tok


def _fetch_v1_email(customer_id):
    """Pull EmailAddr from v1 GetCustomer/{id}. Returns '' on any failure so
    signup.html's 'MISSING_VERGENT_EMAIL' path fires with a useful message."""
    if not customer_id:
        return ""
    tok = _get_v1_token()
    if not tok:
        return ""
    status, body = _v1_http(f"/V1/GetCustomer/{customer_id}", "GET",
                            headers={"Token": tok})
    if status in (401, 403):
        # Token may have rotated — refresh once and retry.
        global _v1_token_exp
        _v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, body = _v1_http(f"/V1/GetCustomer/{customer_id}", "GET",
                                    headers={"Token": tok2})
    if status != 200 or not isinstance(body, dict):
        return ""
    return (body.get("EmailAddr") or "").strip()


def _to_iso_datetime(ymd: str) -> str:
    """Convert 'YYYY-MM-DD' to 'YYYY-MM-DDT00:00:00Z' for Vergent's shape.

    Already-ISO inputs pass through unchanged.
    """
    ymd = (ymd or "").strip()
    if not ymd:
        return ""
    if "T" in ymd:
        return ymd
    return f"{ymd}T00:00:00Z"


def _name_matches(customer: dict, first: str, last: str) -> bool:
    first_v = (customer.get("firstName") or "").strip().lower()
    last_v = (customer.get("lastName") or "").strip().lower()
    return first_v == first and last_v == last


def _cognito_user_exists(email: str, vergent_customer_id: str) -> bool:
    """Return True if either identifier is already tied to a portal account.

    Cognito's ListUsers Filter only supports a fixed set of standard attrs —
    custom:vergentCustomerId is NOT filterable. So we do:
      1. Fast path: filter by email (Cognito-native, O(1))
      2. Slow path: paginate the pool and match vergentCustomerId client-side
    Once user count outgrows ~1000, move path 2 to a DynamoDB index.
    """
    if not _POOL_ID:
        return False
    email = (email or "").strip().lower()
    vcid  = (vergent_customer_id or "").strip()
    if not email and not vcid:
        return False

    # Path 1 — email filter
    if email:
        try:
            resp = _cognito.list_users(
                UserPoolId=_POOL_ID,
                Filter=f'email = "{email}"',
                Limit=1,
            )
            if resp.get("Users"):
                return True
        except ClientError as e:
            _log.warning("cognito list_users by email failed: %s", e)

    # Path 2 — paginated scan for matching custom attribute
    if not vcid:
        return False
    pagination_token = None
    scanned = 0
    MAX_SCAN = 5000
    while scanned < MAX_SCAN:
        kwargs = {"UserPoolId": _POOL_ID, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = _cognito.list_users(**kwargs)
        except ClientError as e:
            _log.warning("cognito list_users scan failed: %s", e)
            return False
        for u in resp.get("Users", []):
            for a in u.get("Attributes", []):
                if a.get("Name") == "custom:vergentCustomerId" and a.get("Value") == vcid:
                    return True
        scanned += len(resp.get("Users", []))
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    return False


def _to_iso_datetime(ymd: str) -> str:
    """Convert 'YYYY-MM-DD' to 'YYYY-MM-DDT00:00:00Z' for Vergent's shape.

    Already-ISO inputs pass through unchanged.
    """
    ymd = (ymd or "").strip()
    if not ymd:
        return ""
    if "T" in ymd:
        return ymd
    return f"{ymd}T00:00:00Z"


def _name_matches(customer: dict, first: str, last: str) -> bool:
    first_v = (customer.get("firstName") or "").strip().lower()
    last_v = (customer.get("lastName") or "").strip().lower()
    return first_v == first and last_v == last


def _cognito_user_exists(email: str, vergent_customer_id: str) -> bool:
    """Return True if either identifier is already tied to a portal account.

    Cognito's ListUsers Filter only supports a fixed set of standard attrs —
    custom:vergentCustomerId is NOT filterable. So we do:
      1. Fast path: filter by email (Cognito-native, O(1))
      2. Slow path: paginate the pool and match vergentCustomerId client-side
    Once user count outgrows ~1000, move path 2 to a DynamoDB index.
    """
    if not _POOL_ID:
        return False
    email = (email or "").strip().lower()
    vcid  = (vergent_customer_id or "").strip()
    if not email and not vcid:
        return False

    # Path 1 — email filter
    if email:
        try:
            resp = _cognito.list_users(
                UserPoolId=_POOL_ID,
                Filter=f'email = "{email}"',
                Limit=1,
            )
            if resp.get("Users"):
                return True
        except ClientError as e:
            _log.warning("cognito list_users by email failed: %s", e)

    # Path 2 — paginated scan for matching custom attribute
    if not vcid:
        return False
    pagination_token = None
    scanned = 0
    MAX_SCAN = 5000
    while scanned < MAX_SCAN:
        kwargs = {"UserPoolId": _POOL_ID, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = _cognito.list_users(**kwargs)
        except ClientError as e:
            _log.warning("cognito list_users scan failed: %s", e)
            return False
        for u in resp.get("Users", []):
            for a in u.get("Attributes", []):
                if a.get("Name") == "custom:vergentCustomerId" and a.get("Value") == vcid:
                    return True
        scanned += len(resp.get("Users", []))
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    return False
