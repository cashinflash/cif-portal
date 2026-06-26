"""
Server-side MFA login flow (email via SES, SMS via Telnyx Verify).

Routes (no JWT auth — these ARE the auth endpoints):
  POST /api/auth/login        {email, password}
  POST /api/auth/send-code    {mfaSession, channel}   channel = "email" | "sms"
  POST /api/auth/verify-code  {mfaSession, code}

Delivery channels:
  email  -> SES SendEmail with a 6-digit code we generate ourselves
  sms    -> Telnyx Verify (start + check). Telnyx generates the code and
            texts it from our toll-free number; we just record that the
            session is in a verify state so /verify-code routes the
            submitted code back to Telnyx for validation.

Session state (DynamoDB, 5-min TTL):
  - For our own code (email): we store sha256(code) in `codeHash` and
    compare on verify.
  - For Vergent PIN (sms): we don't store the code; verification calls
    Vergent /api/Communication/VerifyPin with the submitted pin.

Cognito tokens live in DDB until the user enters the right code, so
MFA cannot be bypassed by hitting Cognito directly.

Environment:
  COGNITO_USER_POOL_ID       us-east-1_U508xOs95
  COGNITO_APP_CLIENT_ID      1mddi61n19hftaldt9t3r622b
  MFA_SESSION_TABLE          cif-portal-mfa-sessions-dev
  (MFA_EMAIL_SENDER removed — sender is hardcoded to no-reply@cashinflash.com)
  MFA_CODE_TTL_SECS          300
  VERGENT_V1_BASE_URL        https://shared.vergentlms.com/api/api
  VERGENT_APIM_BASE_URL      https://prod.apim.vergentlms.com/external/shared
  VERGENT_SECRET_ARN         arn:...cif-portal/vergent/credentials

IAM: cognito AdminInitiateAuth/AdminGetUser on the pool,
     dynamodb read/write on the session table,
     ses SendEmail,
     secretsmanager GetSecretValue on the Vergent secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from handlers import telnyx_verify  # Verify (turnkey OTP) — current SMS channel
from handlers import resend_email   # Resend transactional email — replaced SES

log = logging.getLogger()
log.setLevel(logging.INFO)

USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
APP_CLIENT_ID = os.environ["COGNITO_APP_CLIENT_ID"]
TABLE = os.environ.get("MFA_SESSION_TABLE", "cif-portal-mfa-sessions-dev")
# Hardcoded to the DKIM-verified domain (cashinflash.com). The env-var
# override existed historically but only ever held a stale, unverified
# Gmail address that broke email-MFA delivery — removing it makes the
# stale Lambda env var a no-op.
EMAIL_SENDER = "no-reply@cashinflash.com"
CODE_TTL = int(os.environ.get("MFA_CODE_TTL_SECS", "300"))
MAX_ATTEMPTS = 3

V1_BASE = os.environ.get("VERGENT_V1_BASE_URL", "https://shared.vergentlms.com/api/api").rstrip("/")
APIM_BASE = os.environ.get("VERGENT_APIM_BASE_URL", "https://prod.apim.vergentlms.com/external/shared").rstrip("/")
VERGENT_SECRET_ARN = os.environ.get("VERGENT_SECRET_ARN", "")

cognito = boto3.client("cognito-idp")
ddb = boto3.client("dynamodb")
ses = boto3.client("ses")
_secrets = boto3.client("secretsmanager")

# Service-token caches across warm invocations.
_creds_cache: Optional[Dict[str, str]] = None
_v1_token: Optional[str] = None
_v1_token_exp: float = 0.0
_apim_token: Optional[str] = None
_apim_token_exp: float = 0.0
TOKEN_TTL = 60 * 60

ALLOWED_ORIGIN = os.environ.get(
    "PORTAL_ORIGIN", "https://d1zucrj1ouu3c.cloudfront.net"
)

CORS = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Max-Age": "300",
    "Vary": "Origin",
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def _resp(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=str)}


def _parse(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return {}


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _new_session_id() -> str:
    return secrets.token_urlsafe(32)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    name, _, domain = email.partition("@")
    if len(name) <= 2:
        return f"{name[:1]}***@{domain}"
    return f"{name[:2]}***{name[-1]}@{domain}"


def _mask_phone(digits: str) -> str:
    digits = "".join(c for c in (digits or "") if c.isdigit())
    if len(digits) >= 4:
        return f"•••-•••-{digits[-4:]}"
    return ""


def _get_vergent_creds() -> Optional[Dict[str, str]]:
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    if not VERGENT_SECRET_ARN:
        return None
    try:
        resp = _secrets.get_secret_value(SecretId=VERGENT_SECRET_ARN)
    except ClientError as e:
        log.warning("vergent secret read failed: %s", e.response.get("Error", {}).get("Code"))
        return None
    p = json.loads(resp["SecretString"])
    _creds_cache = {"logonName": p["logonName"], "password": p["password"], "xApiKey": p["xApiKey"]}
    return _creds_cache


def _http(url: str, method: str = "GET", body: Optional[Dict[str, Any]] = None,
          headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Tuple[int, Optional[Any], str]:
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
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        log.warning("vergent %s %s -> %s: %s", method, url, e.code, raw[:200])
        return e.code, None, raw
    except Exception as exc:
        log.error("vergent %s %s network: %s", method, url, exc)
        return 0, None, ""


def _get_v1_token() -> Optional[str]:
    global _v1_token, _v1_token_exp
    if _v1_token and _v1_token_exp > time.time():
        return _v1_token
    creds = _get_vergent_creds()
    if not creds:
        return None
    status, body, _ = _http(
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


def _get_apim_token() -> Optional[str]:
    global _apim_token, _apim_token_exp
    if _apim_token and _apim_token_exp > time.time():
        return _apim_token
    creds = _get_vergent_creds()
    if not creds:
        return None
    status, body, _ = _http(
        f"{APIM_BASE}/api/authenticate", "POST",
        body={"userName": creds["logonName"], "password": creds["password"]},
        headers={"x-api-key": creds["xApiKey"]},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    tok = body.get("auth_token")
    if tok:
        _apim_token = tok
        _apim_token_exp = time.time() + TOKEN_TTL
    return tok


def _get_vergent_phone(customer_id: str) -> Optional[str]:
    """Pull primary phone digits from Vergent v1 GetCustomerData."""
    tok = _get_v1_token()
    if not tok:
        return None
    status, body, _ = _http(
        f"{V1_BASE}/V1/GetCustomerData/{customer_id}", "GET",
        headers={"Token": tok},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    phones = body.get("custPhones") or []
    if not isinstance(phones, list) or not phones:
        return None
    primary = next((p for p in phones if isinstance(p, dict) and p.get("is_primary")), phones[0])
    raw = (primary or {}).get("number") or ""
    digits = "".join(c for c in raw if c.isdigit())
    return digits if len(digits) >= 10 else None


def _find_vergent_customer_id_by_email(email: str) -> Optional[str]:
    """Search Vergent for a customer with the given email address.
    Returns the Vergent customer ID (string) or None.

    Used by the login flow as a fallback when Cognito doesn't recognize
    the email — admin may have just changed the email in Vergent and
    the customer's Cognito record hasn't been synced yet.
    """
    if not email:
        return None
    tok = _get_v1_token()
    if not tok:
        return None
    # Vergent v1 GetCustomers supports filtering by email.
    status, body, _raw = _http(
        f"{V1_BASE}/V1/GetCustomers?email={urllib.parse.quote(email)}",
        "GET",
        headers={"Token": tok},
    )
    if status != 200:
        return None
    # Response can be a list or a wrapped {Items:[...]} or {Customers:[...]}.
    items = body if isinstance(body, list) else None
    if isinstance(body, dict):
        items = body.get("Items") or body.get("Customers") or body.get("customers")
    if not isinstance(items, list) or not items:
        return None
    first = items[0] if isinstance(items[0], dict) else None
    if not first:
        return None
    cid = first.get("id") or first.get("Id") or first.get("customer_id") or first.get("CustomerId")
    return str(cid) if cid is not None else None


def _find_cognito_user_by_vergent_id(vergent_cid: str) -> Optional[Dict[str, Any]]:
    """Find the single Cognito user whose custom:vergentCustomerId
    attribute matches. Returns the same shape as _admin_get_user, or
    None if no match.

    Cognito's ListUsers filter only supports a fixed set of standard
    attributes (email, phone_number, sub, etc.) — custom attributes
    can't be filtered server-side. So we paginate through the user
    pool and match client-side. OK for small pools (< ~10k users).
    """
    if not vergent_cid:
        return None
    target = str(vergent_cid)
    pagination_token: Optional[str] = None
    scanned = 0
    while True:
        kwargs: Dict[str, Any] = {"UserPoolId": USER_POOL_ID, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = cognito.list_users(**kwargs)
        except ClientError as e:
            log.warning("list_users failed code=%s",
                        e.response.get("Error", {}).get("Code", "?"))
            return None
        users = resp.get("Users", []) or []
        for u in users:
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            if attrs.get("custom:vergentCustomerId") == target:
                log.info("found cognito user for vergent_cid=%s (scanned=%d)",
                         target, scanned + len(users))
                return {"Username": u.get("Username"), "Attrs": attrs, "Status": u.get("UserStatus")}
        scanned += len(users)
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    log.info("no cognito user for vergent_cid=%s (scanned=%d)", target, scanned)
    return None


def _admin_set_email(username: str, new_email: str) -> bool:
    """Update a Cognito user's email attribute and mark verified.
    Returns True on success."""
    try:
        cognito.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": new_email},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        return True
    except ClientError as e:
        log.warning("admin_update_user_attributes failed code=%s sub=%s",
                    e.response.get("Error", {}).get("Code", "?"), username)
        return False


# (Vergent SMS helpers removed — Communication/RequestPinByText returned
# SKIP for every combination we tried. SMS now goes through Telnyx Verify,
# see handlers/telnyx_verify.py.)


# ─────────────────────────────────────────
# Cognito
# ─────────────────────────────────────────
def _admin_get_user(username: str) -> Dict[str, Any]:
    try:
        u = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=username)
    except ClientError:
        return {}
    attrs = {a["Name"]: a["Value"] for a in u.get("UserAttributes", [])}
    return {"Username": u.get("Username"), "Attrs": attrs, "Status": u.get("UserStatus")}


def _admin_initiate_password_auth(email: str, password: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    try:
        r = cognito.admin_initiate_auth(
            UserPoolId=USER_POOL_ID,
            ClientId=APP_CLIENT_ID,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except ClientError as e:
        return None, e.response.get("Error", {}).get("Code", "Unknown")
    ar = r.get("AuthenticationResult")
    if not ar:
        return None, r.get("ChallengeName") or "ChallengeRequired"
    return {
        "IdToken": ar.get("IdToken"),
        "AccessToken": ar.get("AccessToken"),
        "RefreshToken": ar.get("RefreshToken"),
        "ExpiresIn": ar.get("ExpiresIn"),
    }, None


# ─────────────────────────────────────────
# Session store
# ─────────────────────────────────────────
def _store_session(session_id: str, *, email: str, sub: str,
                   tokens: Dict[str, str],
                   phone_digits: Optional[str],
                   vergent_customer_id: Optional[str]) -> None:
    now = int(time.time())
    item = {
        "sessionId": {"S": session_id},
        "createdAt": {"N": str(now)},
        "expiresAt": {"N": str(now + CODE_TTL)},
        "email": {"S": email},
        "sub": {"S": sub or ""},
        "mode": {"S": "pending"},
        "channel": {"S": "pending"},
        "attempts": {"N": "0"},
        "tokens": {"S": json.dumps(tokens)},
    }
    if phone_digits:
        item["phone"] = {"S": phone_digits}
    if vergent_customer_id:
        item["vergentCustomerId"] = {"S": vergent_customer_id}
    ddb.put_item(TableName=TABLE, Item=item)


def _load_session(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = ddb.get_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
    except ClientError:
        return None
    item = r.get("Item")
    if not item:
        return None
    now = int(time.time())
    if int(item["expiresAt"]["N"]) <= now:
        ddb.delete_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
        return None
    return {
        "sessionId": session_id,
        "email": item["email"]["S"],
        "sub": item.get("sub", {}).get("S", ""),
        "mode": item.get("mode", {}).get("S", "pending"),
        "channel": item.get("channel", {}).get("S", "pending"),
        "codeHash": item.get("codeHash", {}).get("S"),
        "attempts": int(item["attempts"]["N"]),
        "tokens": json.loads(item["tokens"]["S"]),
        "phone": item.get("phone", {}).get("S"),
        "vergentCustomerId": item.get("vergentCustomerId", {}).get("S"),
        "expiresAt": int(item["expiresAt"]["N"]),
    }


def _arm_our_code(session_id: str, code_hash: str, channel: str) -> None:
    now = int(time.time())
    ddb.update_item(
        TableName=TABLE, Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET codeHash = :c, #m = :m, #ch = :ch, attempts = :z, expiresAt = :e",
        ExpressionAttributeNames={"#m": "mode", "#ch": "channel"},
        ExpressionAttributeValues={
            ":c": {"S": code_hash},
            ":m": {"S": "our_code"},
            ":ch": {"S": channel},
            ":z": {"N": "0"},
            ":e": {"N": str(now + CODE_TTL)},
        },
    )


def _arm_verify_sms(session_id: str) -> None:
    """Mark the session as 'Telnyx Verify is now tracking this phone'. No
    code hash on our side — Telnyx stores + validates the code."""
    now = int(time.time())
    ddb.update_item(
        TableName=TABLE, Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET #m = :m, #ch = :ch, attempts = :z, expiresAt = :e REMOVE codeHash",
        ExpressionAttributeNames={"#m": "mode", "#ch": "channel"},
        ExpressionAttributeValues={
            ":m": {"S": "verify_sms"},
            ":ch": {"S": "sms"},
            ":z": {"N": "0"},
            ":e": {"N": str(now + CODE_TTL)},
        },
    )


def _bump_attempts(session_id: str, attempts: int) -> None:
    ddb.update_item(
        TableName=TABLE, Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET attempts = :a",
        ExpressionAttributeValues={":a": {"N": str(attempts)}},
    )


def _delete_session(session_id: str) -> None:
    try:
        ddb.delete_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
    except ClientError:
        pass


# ─────────────────────────────────────────
# Trusted-device records ("Remember me on this device")
#
# After a successful MFA verify, if the user opted in, we mint a random
# device token, hand it to the browser (localStorage), and store ONLY its
# sha256 here (namespaced in the same session table, 30-day TTL). On the
# next login we re-verify the password as always, then — if a valid,
# non-expired token bound to the SAME user is presented — skip the OTP
# step. A stolen token is useless without the password; a table leak
# exposes only hashes. The window slides forward on each trusted login.
# ─────────────────────────────────────────
DEVICE_TRUST_TTL = int(os.environ.get("DEVICE_TRUST_TTL_SECS", str(30 * 24 * 60 * 60)))


def _device_key(token: str) -> str:
    return "device#" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_trusted_device(sub: str, email: str) -> Optional[str]:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    try:
        ddb.put_item(TableName=TABLE, Item={
            "sessionId": {"S": _device_key(token)},
            "kind": {"S": "device"},
            "sub": {"S": sub or ""},
            "email": {"S": (email or "").lower()},
            "createdAt": {"N": str(now)},
            "expiresAt": {"N": str(now + DEVICE_TRUST_TTL)},
        })
    except ClientError:
        return None
    return token


def _check_trusted_device(token: str, *, sub: str, email: str) -> bool:
    if not token:
        return False
    try:
        resp = ddb.get_item(
            TableName=TABLE, Key={"sessionId": {"S": _device_key(token)}},
            ConsistentRead=True,
        )
    except ClientError:
        return False
    item = resp.get("Item")
    if not item or item.get("kind", {}).get("S") != "device":
        return False
    if int(item.get("expiresAt", {}).get("N", "0")) <= int(time.time()):
        return False
    # Bind the token to the account that created it. Prefer the stable sub;
    # fall back to email. Constant-time compare on the identifier.
    rec_sub = item.get("sub", {}).get("S", "")
    if rec_sub and sub:
        return hmac.compare_digest(rec_sub, sub)
    rec_email = item.get("email", {}).get("S", "")
    return bool(rec_email) and hmac.compare_digest(rec_email, (email or "").lower())


def _renew_trusted_device(token: str) -> None:
    try:
        ddb.update_item(
            TableName=TABLE, Key={"sessionId": {"S": _device_key(token)}},
            UpdateExpression="SET expiresAt = :e",
            ExpressionAttributeValues={":e": {"N": str(int(time.time()) + DEVICE_TRUST_TTL)}},
        )
    except ClientError:
        pass


# ─────────────────────────────────────────
# Senders
# ─────────────────────────────────────────
def _send_email(to: str, code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body_text = (
        f"Cash in Flash — Sign-in code\n\n"
        f"Your sign-in code is: {code}\n\n"
        f"Didn't try to sign in? You can ignore this email. If you think "
        f"someone is trying to access your account, reset your password at "
        f"https://portal.cashinflash.com/forgot.html.\n\n"
        f"Please do not share this code with anyone. A Cash in Flash Representative "
        f"will NEVER ask you to provide them with your sign-in code.\n\n"
        f"Questions? Call our Customer Service Team at (888) 999-9859.\n\n"
        f"---\n"
        f"This email message contains information from Cash in Flash and is confidential. "
        f"If you received this email in error, please notify us at (888) 999-9859 or "
        f"info@cashinflash.com.\n\n"
        f"© 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.\n"
        f"Cash in Flash, 13937B Van Nuys Blvd, Arleta, CA 91331"
    )
    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:34px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 40px 20px;">
          <h1 style="margin:0 0 16px;font-size:21px;font-weight:700;color:#0E8741;line-height:1.25;">Your sign-in code is: {code}</h1>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Didn't try to sign in? Please <a href="https://d1zucrj1ouu3c.cloudfront.net/forgot.html" style="color:#0E8741;text-decoration:underline;">reset your password</a>.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Please do not provide this code to anyone. A Cash in Flash Representative will <strong>never</strong> ask you to provide them with your sign-in code.</p>
          <p style="margin:0 0 4px;font-size:14px;line-height:1.55;color:#1a1a2e;">If you still have questions, contact our Customer Service Team at <a href="tel:+18889999859" style="color:#1a1a2e;font-weight:600;text-decoration:underline;">(888) 999-9859</a>.</p>
        </td></tr>
        <tr><td style="padding:22px 40px 34px;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 10px;">This email message contains information from Cash in Flash and is confidential. The included information is intended only for the use of the individual or entity named above. If you are not the intended recipient, be aware that any disclosure, copying, distribution, or use of the contents of this message is prohibited.</p>
          <p style="margin:0 0 10px;">If you received this email in error, please notify us immediately by telephone at <a href="tel:+18889999859" style="color:#6b7280;text-decoration:underline;">(888) 999-9859</a> or email at <a href="mailto:info@cashinflash.com" style="color:#6b7280;text-decoration:underline;">info@cashinflash.com</a>.</p>
          <p style="margin:0 0 10px;">&copy; 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.</p>
          <p style="margin:0 0 4px;">This email was sent by Cash in Flash<br>13937B Van Nuys Blvd, Arleta, CA 91331</p>
          <p style="margin:10px 0 0;"><a href="https://cashinflash.com/privacy/" style="color:#0E8741;text-decoration:underline;">Privacy Policy</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    # Send via Resend (replaced AWS SES after AWS denied production
    # access twice). The handler returns the same (ok, code, msg)
    # tuple shape so the /send-code route surfaces error details to
    # DevTools the same way it did with SES.
    return resend_email.send(
        to=to,
        subject="Your Cash in Flash sign-in code",
        text=body_text,
        html=body_html,
    )


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def _login(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return _resp(400, {"error": "missing_credentials"})

    tokens, err = _admin_initiate_password_auth(email, password)

    # Email-change instant-sync fallback (Phase H follow-up):
    # If Cognito doesn't recognize this email but Vergent does, the
    # customer most likely just had their email updated by an admin
    # and Cognito hasn't been synced yet. Find their Cognito user by
    # Vergent customer ID, retry password auth with their current
    # (old) Cognito email, and on success update Cognito to the new
    # email so the next login uses it. Then re-authenticate to get
    # tokens whose JWT email claim matches what they typed.
    if not tokens and err in ("UserNotFoundException", "NotAuthorizedException"):
        log.info("login fallback start email=%s err=%s", _mask_email(email), err)
        vergent_cid = _find_vergent_customer_id_by_email(email)
        log.info("login fallback vergent lookup email=%s -> cid=%s",
                 _mask_email(email), vergent_cid or "(none)")
        if vergent_cid:
            cognito_user = _find_cognito_user_by_vergent_id(vergent_cid)
            old_email = (cognito_user or {}).get("Attrs", {}).get("email") or ""
            log.info("login fallback cognito lookup cid=%s -> old_email=%s",
                     vergent_cid, _mask_email(old_email) if old_email else "(none)")
            if old_email and old_email.lower() != email:
                retry_tokens, retry_err = _admin_initiate_password_auth(old_email, password)
                log.info("login fallback retry-auth old=%s -> %s",
                         _mask_email(old_email), "ok" if retry_tokens else f"err:{retry_err}")
                if retry_tokens:
                    username = cognito_user.get("Username") or ""
                    if _admin_set_email(username, email):
                        log.info("login email synced cid=%s old=%s new=%s",
                                 vergent_cid, _mask_email(old_email), _mask_email(email))
                        # Re-auth with the new email so the JWT carries
                        # the correct email claim.
                        tokens, err = _admin_initiate_password_auth(email, password)
                        if not tokens:
                            # Cognito sometimes needs a moment to propagate
                            # the alias change. Fall back to the retry
                            # tokens (which work, just with the old email
                            # claim — the next /api/my-profile call will
                            # re-sync if needed).
                            log.info("login post-sync re-auth not ready (%s); using retry tokens", err)
                            tokens, err = retry_tokens, None
                        else:
                            log.info("login post-sync re-auth ok email=%s", _mask_email(email))

    if not tokens:
        log.info("login failed for %s: %s", _mask_email(email), err)
        return _resp(401, {"error": "invalid_credentials"})

    user = _admin_get_user(email)
    sub = user.get("Attrs", {}).get("sub", "")
    vergent_cid = user.get("Attrs", {}).get("custom:vergentCustomerId")

    # "Remember me": if the browser presents a valid trusted-device token for
    # THIS user, the verified password above is our factor for the session —
    # skip the OTP step and return Cognito tokens directly.
    device_token = (body.get("deviceToken") or "").strip()
    if device_token:
        if _check_trusted_device(device_token, sub=sub, email=email):
            _renew_trusted_device(device_token)
            log.info("login device-trusted (MFA skipped) for %s", _mask_email(email))
            return _resp(200, {
                "authenticated": True,
                "idToken": tokens.get("IdToken"),
                "accessToken": tokens.get("AccessToken"),
                "refreshToken": tokens.get("RefreshToken"),
                "expiresIn": tokens.get("ExpiresIn") or 3600,
            })
        log.info("login device-token present but invalid for %s -> MFA", _mask_email(email))

    # Prefer the Vergent phone (what the customer actually uses) over Cognito.
    phone_digits = None
    if vergent_cid:
        phone_digits = _get_vergent_phone(vergent_cid)
    if not phone_digits:
        fallback = user.get("Attrs", {}).get("phone_number") or ""
        f = "".join(c for c in fallback if c.isdigit())
        if len(f) >= 10:
            phone_digits = f

    session_id = _new_session_id()
    _store_session(
        session_id,
        email=email, sub=sub, tokens=tokens,
        phone_digits=phone_digits, vergent_customer_id=vergent_cid,
    )

    # SMS (Telnyx) arrives instantly, so list it FIRST as the default/
    # fastest option; email (Resend) can lag on delivery. SMS is surfaced
    # whenever we have a phone — if Telnyx creds aren't configured,
    # /send-code returns a clean delivery_failed_sms rather than hiding it.
    channels = []
    if phone_digits:
        channels.append({"key": "sms", "label": "Text message", "target": _mask_phone(phone_digits)})
    channels.append({"key": "email", "label": "Email", "target": _mask_email(email)})

    return _resp(200, {
        "mfaSession": session_id,
        "channels": channels,
        "deliveredTo": None,
        "expiresInSec": CODE_TTL,
    })


def _send_code(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    session_id = body.get("mfaSession") or ""
    channel = (body.get("channel") or "").strip().lower()
    if channel not in ("email", "sms"):
        return _resp(400, {"error": "invalid_channel"})

    s = _load_session(session_id)
    if not s:
        return _resp(401, {"error": "session_expired"})

    if channel == "email":
        code = _new_code()
        _arm_our_code(session_id, _hash_code(code), channel="email")
        ok, ses_code, ses_msg = _send_email(s["email"], code)
        if not ok:
            body: Dict[str, Any] = {"error": "delivery_failed_email"}
            if ses_code:
                body["sesCode"] = ses_code
            if ses_msg:
                body["sesMessage"] = ses_msg
            return _resp(502, body)
        return _resp(200, {"ok": True, "channel": "email", "expiresInSec": CODE_TTL})

    # channel == sms — Telnyx Verify generates, delivers, and validates the
    # code. We don't store the code; we just mark the session so /verify-code
    # knows to route the submitted code back to Telnyx for validation.
    phone = s.get("phone")
    if not phone:
        return _resp(400, {"error": "no_phone_on_file"})
    ok, detail = telnyx_verify.start_sms(to=phone)
    if not ok:
        log.warning("telnyx verify start failed: %s", detail)
        return _resp(502, {"error": "delivery_failed_sms", "detail": detail})
    _arm_verify_sms(session_id)
    return _resp(200, {"ok": True, "channel": "sms", "expiresInSec": CODE_TTL})


def _verify_code(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    session_id = body.get("mfaSession") or ""
    code = (body.get("code") or "").strip()
    if not session_id or not code:
        return _resp(400, {"error": "missing_fields"})

    s = _load_session(session_id)
    if not s:
        return _resp(401, {"error": "session_expired"})

    mode = s.get("mode")
    if mode == "our_code":
        ok = hmac.compare_digest(_hash_code(code), s.get("codeHash") or "")
    elif mode == "verify_sms":
        phone = s.get("phone") or ""
        approved, status_str = telnyx_verify.check(phone, code)
        if status_str == "expired":
            _delete_session(session_id)
            return _resp(401, {"error": "code_expired"})
        ok = approved
    else:
        # Session exists but /send-code wasn't called yet.
        return _resp(400, {"error": "no_code_sent"})

    if not ok:
        attempts = s["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            _delete_session(session_id)
            return _resp(401, {"error": "too_many_attempts"})
        _bump_attempts(session_id, attempts)
        return _resp(401, {"error": "invalid_code", "attemptsRemaining": MAX_ATTEMPTS - attempts})

    tokens = s["tokens"]

    # "Remember me on this device": mint a 30-day trusted-device token so the
    # next login from this browser skips the OTP step (password still required).
    trusted_device = None
    if body.get("rememberDevice"):
        trusted_device = _issue_trusted_device(s.get("sub", ""), s.get("email", ""))

    _delete_session(session_id)
    resp_body = {
        "idToken": tokens.get("IdToken"),
        "accessToken": tokens.get("AccessToken"),
        "refreshToken": tokens.get("RefreshToken"),
        "expiresIn": tokens.get("ExpiresIn") or 3600,
    }
    if trusted_device:
        resp_body["trustedDevice"] = trusted_device
    return _resp(200, resp_body)


# ─────────────────────────────────────────
# Password reset (forgot password)
#
# Replaces the slow Cognito-default ForgotPassword email with our own
# 6-digit code delivered through Resend — same trust model as the login
# MFA code (CSPRNG code, sha256-hashed at rest, constant-time compare,
# 3-try cap, 5-min TTL). On confirm we set the new password directly via
# AdminSetUserPassword(Permanent=True).
#
#   POST /api/auth/forgot/start    {email}
#       -> {ok, resetSession, masked, expiresInSec}   (always, even if the
#          email isn't a real account — no enumeration oracle)
#   POST /api/auth/forgot/confirm  {resetSession, code, newPassword}
#       -> {ok}  on success
# ─────────────────────────────────────────
def _store_reset_session(session_id: str, *, email: str, username: str,
                         code_hash: str, real: bool) -> None:
    now = int(time.time())
    item = {
        "sessionId": {"S": session_id},
        "createdAt": {"N": str(now)},
        "expiresAt": {"N": str(now + CODE_TTL)},
        "email": {"S": email},
        "mode": {"S": "reset"},
        "attempts": {"N": "0"},
        "codeHash": {"S": code_hash},
        "resetReal": {"BOOL": bool(real)},
    }
    if username:
        item["resetUsername"] = {"S": username}
    ddb.put_item(TableName=TABLE, Item=item)


def _load_reset_session(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = ddb.get_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
    except ClientError:
        return None
    item = r.get("Item")
    if not item:
        return None
    if int(item["expiresAt"]["N"]) <= int(time.time()):
        ddb.delete_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
        return None
    if item.get("mode", {}).get("S") != "reset":
        return None
    return {
        "sessionId": session_id,
        "email": item.get("email", {}).get("S", ""),
        "username": item.get("resetUsername", {}).get("S", ""),
        "codeHash": item.get("codeHash", {}).get("S", ""),
        "attempts": int(item.get("attempts", {}).get("N", "0")),
        "real": item.get("resetReal", {}).get("BOOL", False),
    }


def _send_reset_email(to: str, code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body_text = (
        f"Cash in Flash — Password reset code\n\n"
        f"Your password reset code is: {code}\n\n"
        f"Enter it on the reset page to choose a new password. This code "
        f"expires in 5 minutes.\n\n"
        f"Didn't request this? You can ignore this email — your password "
        f"won't change unless someone enters the code above.\n\n"
        f"Please do not share this code with anyone. A Cash in Flash "
        f"Representative will NEVER ask you for it.\n\n"
        f"Questions? Call our Customer Service Team at (888) 999-9859.\n\n"
        f"---\n"
        f"© 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. "
        f"License #214840.\n"
        f"Cash in Flash, 13937B Van Nuys Blvd, Arleta, CA 91331"
    )
    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:34px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 40px 20px;">
          <h1 style="margin:0 0 16px;font-size:21px;font-weight:700;color:#0E8741;line-height:1.25;">Your password reset code is: {code}</h1>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Enter it on the reset page to choose a new password. This code expires in 5 minutes.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Didn't request this? You can safely ignore this email — your password won't change unless someone enters the code above.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Please do not provide this code to anyone. A Cash in Flash Representative will <strong>never</strong> ask you for it.</p>
          <p style="margin:0 0 4px;font-size:14px;line-height:1.55;color:#1a1a2e;">Questions? Call our Customer Service Team at <a href="tel:+18889999859" style="color:#1a1a2e;font-weight:600;text-decoration:underline;">(888) 999-9859</a>.</p>
        </td></tr>
        <tr><td style="padding:22px 40px 34px;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 10px;">&copy; 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.</p>
          <p style="margin:0 0 4px;">This email was sent by Cash in Flash<br>13937B Van Nuys Blvd, Arleta, CA 91331</p>
          <p style="margin:10px 0 0;"><a href="https://cashinflash.com/privacy/" style="color:#0E8741;text-decoration:underline;">Privacy Policy</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return resend_email.send(
        to=to,
        subject="Your Cash in Flash password reset code",
        text=body_text,
        html=body_html,
    )


def _forgot_start(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    email = (body.get("email") or "").strip().lower()
    session_id = _new_session_id()
    code = _new_code()
    code_hash = _hash_code(code)

    # Resolve the user WITHOUT leaking existence to the caller. We always
    # mint a session and return the same shape; only a real account gets
    # an email. A bogus/typo'd email advances to the code screen too but
    # no code ever arrives (and confirm can never succeed for it).
    user = _admin_get_user(email) if (email and "@" in email) else {}
    exists = bool(user)
    username = user.get("Username") or email if exists else ""
    _store_reset_session(session_id, email=email, username=username,
                         code_hash=code_hash, real=exists)

    if exists:
        ok, _c, _m = _send_reset_email(email, code)
        if not ok:
            log.warning("reset email delivery failed for %s", _mask_email(email))
    else:
        log.info("reset requested for unknown email %s (no-op)", _mask_email(email))

    return _resp(200, {
        "ok": True,
        "resetSession": session_id,
        "masked": _mask_email(email),
        "expiresInSec": CODE_TTL,
    })


def _forgot_confirm(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    session_id = body.get("resetSession") or ""
    code = (body.get("code") or "").strip()
    new_password = body.get("newPassword") or ""
    if not session_id or not code or not new_password:
        return _resp(400, {"error": "missing_fields"})

    s = _load_reset_session(session_id)
    if not s:
        return _resp(401, {"error": "session_expired"})

    code_ok = hmac.compare_digest(_hash_code(code), s.get("codeHash") or "")
    # A no-op session (bogus email) is treated exactly like a wrong code so
    # /confirm can't be used to probe which emails are real accounts.
    if not code_ok or not s.get("real"):
        attempts = s["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            _delete_session(session_id)
            return _resp(401, {"error": "too_many_attempts"})
        _bump_attempts(session_id, attempts)
        return _resp(401, {"error": "invalid_code", "attemptsRemaining": MAX_ATTEMPTS - attempts})

    username = s.get("username") or s.get("email")
    try:
        cognito.admin_set_user_password(
            UserPoolId=USER_POOL_ID,
            Username=username,
            Password=new_password,
            Permanent=True,
        )
    except ClientError as e:
        err = e.response.get("Error", {}).get("Code", "")
        if err == "InvalidPasswordException":
            return _resp(400, {"error": "invalid_password"})
        log.warning("admin_set_user_password failed: %s", err)
        return _resp(500, {"error": "reset_failed"})

    _delete_session(session_id)
    return _resp(200, {"ok": True})


# ─────────────────────────────────────────
# Signup (server-side, code delivered via Resend)
#
# Replaces the client-side Cognito SignUp (whose confirmation email is on
# Cognito's slow default path) with: create the user via AdminCreateUser
# (email SUPPRESSED, PreSignUp still validates email==Vergent / dedup),
# deliver our own 6-digit code through Resend, then on confirm set the
# chosen password permanent + mark email_verified. Same trust model as
# the login MFA / reset codes.
#
#   POST /api/auth/signup/start    {email, password, firstName, lastName, vergentCustomerId}
#   POST /api/auth/signup/confirm  {signupSession, code, password}
# ─────────────────────────────────────────
_SIGNUP_LAMBDA_CODES = (
    "EMAIL_MISMATCH", "MISSING_VERGENT_EMAIL", "DUPLICATE_EMAIL",
    "DUPLICATE_VERGENT_CUSTOMER", "VERGENT_UNAVAILABLE",
)


def _password_ok(pw: str) -> bool:
    return (
        len(pw or "") >= 10
        and any(c.isupper() for c in pw)
        and any(c.islower() for c in pw)
        and any(c.isdigit() for c in pw)
        and any((not c.isalnum()) for c in pw)
    )


def _temp_password() -> str:
    # Strong throwaway temp password (immediately replaced at confirm).
    return "Aa1!" + secrets.token_urlsafe(24)


def _user_status(email: str) -> Optional[str]:
    u = _admin_get_user(email)
    return u.get("Status") if u else None


def _store_signup_session(session_id: str, *, email: str, code_hash: str) -> None:
    now = int(time.time())
    ddb.put_item(TableName=TABLE, Item={
        "sessionId": {"S": session_id},
        "createdAt": {"N": str(now)},
        "expiresAt": {"N": str(now + CODE_TTL)},
        "email": {"S": email},
        "mode": {"S": "signup"},
        "attempts": {"N": "0"},
        "codeHash": {"S": code_hash},
    })


def _load_signup_session(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = ddb.get_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
    except ClientError:
        return None
    item = r.get("Item")
    if not item:
        return None
    if int(item["expiresAt"]["N"]) <= int(time.time()):
        ddb.delete_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
        return None
    if item.get("mode", {}).get("S") != "signup":
        return None
    return {
        "sessionId": session_id,
        "email": item.get("email", {}).get("S", ""),
        "codeHash": item.get("codeHash", {}).get("S", ""),
        "attempts": int(item.get("attempts", {}).get("N", "0")),
    }


def _send_signup_email(to: str, code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body_text = (
        f"Cash in Flash — Confirm your account\n\n"
        f"Your verification code is: {code}\n\n"
        f"Enter it to finish creating your Cash in Flash account. This code "
        f"expires in 5 minutes.\n\n"
        f"Didn't try to create an account? You can safely ignore this email.\n\n"
        f"Please do not share this code with anyone. A Cash in Flash "
        f"Representative will NEVER ask you for it.\n\n"
        f"Questions? Call our Customer Service Team at (888) 999-9859.\n\n"
        f"---\n"
        f"© 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. "
        f"License #214840.\n"
        f"Cash in Flash, 13937B Van Nuys Blvd, Arleta, CA 91331"
    )
    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;overflow:hidden;">
        <tr><td align="center" style="background:#0E8741;padding:34px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/cif-mark-white.png" alt="Cash in Flash" width="48" height="50" style="display:block;width:48px;height:50px;border:0;">
        </td></tr>
        <tr><td style="padding:36px 40px 20px;">
          <h1 style="margin:0 0 16px;font-size:21px;font-weight:700;color:#0E8741;line-height:1.25;">Your verification code is: {code}</h1>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Enter it to finish creating your Cash in Flash account. This code expires in 5 minutes.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Didn't try to create an account? You can safely ignore this email.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Please do not provide this code to anyone. A Cash in Flash Representative will <strong>never</strong> ask you for it.</p>
          <p style="margin:0 0 4px;font-size:14px;line-height:1.55;color:#1a1a2e;">Questions? Call our Customer Service Team at <a href="tel:+18889999859" style="color:#1a1a2e;font-weight:600;text-decoration:underline;">(888) 999-9859</a>.</p>
        </td></tr>
        <tr><td style="padding:22px 40px 34px;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 10px;">&copy; 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.</p>
          <p style="margin:0 0 4px;">This email was sent by Cash in Flash<br>13937B Van Nuys Blvd, Arleta, CA 91331</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return resend_email.send(
        to=to,
        subject="Confirm your Cash in Flash account",
        text=body_text,
        html=body_html,
    )


def _signup_start(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    first = (body.get("firstName") or "").strip()
    last = (body.get("lastName") or "").strip()
    vcid = str(body.get("vergentCustomerId") or "").strip()
    if not email or "@" not in email:
        return _resp(400, {"error": "missing_email"})
    if not vcid:
        return _resp(400, {"error": "missing_customer"})
    if not _password_ok(password):
        return _resp(400, {"error": "invalid_password"})

    status = _user_status(email)
    if status and status not in ("FORCE_CHANGE_PASSWORD", "UNCONFIRMED"):
        # Fully-registered account already exists.
        return _resp(409, {"error": "DUPLICATE_EMAIL"})

    if not status:
        attrs = [
            {"Name": "email", "Value": email},
            {"Name": "custom:vergentCustomerId", "Value": vcid},
        ]
        if first:
            attrs.append({"Name": "given_name", "Value": first})
        if last:
            attrs.append({"Name": "family_name", "Value": last})
        try:
            cognito.admin_create_user(
                UserPoolId=USER_POOL_ID,
                Username=email,
                MessageAction="SUPPRESS",
                TemporaryPassword=_temp_password(),
                UserAttributes=attrs,
            )
        except ClientError as e:
            cn = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message") or ""
            if cn == "UsernameExistsException":
                pass  # race / resume — fall through to send a fresh code
            elif cn in ("UserLambdaValidationException", "InvalidLambdaResponseException"):
                for c in _SIGNUP_LAMBDA_CODES:
                    if c in msg:
                        return _resp(400, {"error": c})
                return _resp(400, {"error": "validation_failed"})
            elif cn == "InvalidPasswordException":
                return _resp(400, {"error": "invalid_password"})
            else:
                log.warning("admin_create_user failed: %s", cn)
                return _resp(500, {"error": "signup_failed"})

    session_id = _new_session_id()
    code = _new_code()
    _store_signup_session(session_id, email=email, code_hash=_hash_code(code))
    ok, _c, _m = _send_signup_email(email, code)
    if not ok:
        log.warning("signup email delivery failed for %s", _mask_email(email))
    return _resp(200, {
        "ok": True,
        "signupSession": session_id,
        "masked": _mask_email(email),
        "expiresInSec": CODE_TTL,
    })


def _signup_confirm(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    session_id = body.get("signupSession") or ""
    code = (body.get("code") or "").strip()
    password = body.get("password") or ""
    if not session_id or not code or not password:
        return _resp(400, {"error": "missing_fields"})

    s = _load_signup_session(session_id)
    if not s:
        return _resp(401, {"error": "session_expired"})

    if not hmac.compare_digest(_hash_code(code), s.get("codeHash") or ""):
        attempts = s["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            _delete_session(session_id)
            return _resp(401, {"error": "too_many_attempts"})
        _bump_attempts(session_id, attempts)
        return _resp(401, {"error": "invalid_code", "attemptsRemaining": MAX_ATTEMPTS - attempts})

    email = s["email"]
    try:
        cognito.admin_set_user_password(
            UserPoolId=USER_POOL_ID, Username=email, Password=password, Permanent=True,
        )
        cognito.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID, Username=email,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
    except ClientError as e:
        cn = e.response.get("Error", {}).get("Code", "")
        if cn == "InvalidPasswordException":
            return _resp(400, {"error": "invalid_password"})
        log.warning("signup confirm failed: %s", cn)
        return _resp(500, {"error": "confirm_failed"})

    _delete_session(session_id)
    return _resp(200, {"ok": True})


# ─────────────────────────────────────────
# Onboarding magic-link (one-click portal registration)
#
#   POST /api/auth/onboard/verify    {token}            -> {masked, firstName}
#   POST /api/auth/onboard/complete  {token, password}  -> tokens (auto-login)
#
# A signed, self-contained token is delivered in the customer's onboarding
# email. Holding it proves they control that inbox, so they skip the 6-digit
# code and go straight to setting a password. Token format:
#   base64url(payload) + "." + base64url(hmac_sha256(payload, secret))
# payload = {"cid","email","fn","ln","exp"}. The HMAC secret lives in Secrets
# Manager (ONBOARD_SECRET_ARN). Single-use is implicit: /complete refuses once
# the account is CONFIRMED, so a replayed link can't reset a real customer's
# password. Tokens minted by scripts/mint_onboarding_links.py (admin/offline).
# ─────────────────────────────────────────
ONBOARD_SECRET_ARN = os.environ.get("ONBOARD_SECRET_ARN", "")
ONBOARD_TTL_DAYS = int(os.environ.get("ONBOARD_TTL_DAYS", "14"))
_onboard_secret_cache: Optional[bytes] = None


def _onboard_secret() -> Optional[bytes]:
    global _onboard_secret_cache
    if _onboard_secret_cache is not None:
        return _onboard_secret_cache
    if not ONBOARD_SECRET_ARN:
        return None
    try:
        r = _secrets.get_secret_value(SecretId=ONBOARD_SECRET_ARN)
        raw = r.get("SecretString") or ""
        val = raw
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                val = obj.get("secret") or obj.get("value") or ""
        except Exception:
            pass
        _onboard_secret_cache = (val or "").encode("utf-8")
        return _onboard_secret_cache
    except Exception as e:
        log.warning("onboard secret read failed: %s", e)
        return None


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + ("=" * (-len(s) % 4)))


def _sign_onboard(payload: Dict[str, Any]) -> Optional[str]:
    """Mint a signed onboarding token — mirrors _verify_onboard + the offline
    mint script exactly: base64url(payload) + "." + base64url(hmac_sha256)."""
    secret = _onboard_secret()
    if not secret:
        return None
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + sig


_onboard_apikey_cache: Optional[str] = None


def _onboard_api_key() -> Optional[str]:
    """Shared key the email system presents (X-Api-Key) to mint links. Stored
    alongside the signing key in the onboard secret."""
    global _onboard_apikey_cache
    if _onboard_apikey_cache is not None:
        return _onboard_apikey_cache
    if not ONBOARD_SECRET_ARN:
        return None
    try:
        r = _secrets.get_secret_value(SecretId=ONBOARD_SECRET_ARN)
        obj = json.loads(r.get("SecretString") or "{}")
        _onboard_apikey_cache = (obj.get("apiKey") or "") if isinstance(obj, dict) else ""
        return _onboard_apikey_cache
    except Exception as e:
        log.warning("onboard apiKey read failed: %s", e)
        return None


def _verify_onboard(token: str) -> Optional[Dict[str, Any]]:
    secret = _onboard_secret()
    if not secret or not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64u(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64u_dec(body))
    except Exception:
        return None
    exp = int(payload.get("exp") or 0)
    if exp and exp < int(time.time()):
        return None
    return payload


def _vergent_get_customer(cid: str) -> Optional[Dict[str, Any]]:
    """Raw Vergent V1 GetCustomer record for a customer id (or None)."""
    if not cid:
        return None
    tok = _get_v1_token()
    if not tok:
        return None
    st, b2, _r = _http(f"{V1_BASE}/V1/GetCustomer/{cid}", "GET", headers={"Token": tok})
    if st in (401, 403):
        global _v1_token_exp
        _v1_token_exp = 0
        tok = _get_v1_token()
        if tok:
            st, b2, _r = _http(f"{V1_BASE}/V1/GetCustomer/{cid}", "GET", headers={"Token": tok})
    return b2 if (st == 200 and isinstance(b2, dict)) else None


def _vergent_email_for_cid(cid: str) -> Optional[str]:
    """Vergent's on-file email (EmailAddr) for a customer, or None. Lets
    /onboard/complete key the new account to the verified address so it always
    clears the PreSignUp email-match guard."""
    c = _vergent_get_customer(cid)
    return (c.get("EmailAddr") or "").strip() if c else None


def _onboard_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    p = _verify_onboard((body.get("token") or "").strip())
    if not p:
        return _resp(400, {"error": "invalid_or_expired"})
    email = (p.get("email") or "").strip().lower()
    # Smart link: if they already have a usable login, the page sends them to
    # the sign-in screen instead of the set-password flow.
    status = _user_status(email)
    already = bool(status) and status not in ("FORCE_CHANGE_PASSWORD", "UNCONFIRMED")
    return _resp(200, {
        "ok": True,
        "masked": _mask_email(email),
        "firstName": p.get("fn") or "",
        "alreadyRegistered": already,
    })


def _onboard_mint_link(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/auth/onboard/mint-link   (server-to-server; X-Api-Key header)

    Body: {"email": "..."}  or  {"customerId": "..."}
    Returns {url, masked, alreadyRegistered}. Lets the Resend email system fetch
    a ready onboarding link per customer at send time — no CSV needed.
    """
    headers = {(k or "").lower(): v for k, v in (event.get("headers") or {}).items()}
    provided = (headers.get("x-api-key") or "").strip()
    expected = _onboard_api_key()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        return _resp(401, {"error": "unauthorized"})

    body = _parse(event)
    cid = str(body.get("customerId") or "").strip()
    email_in = (body.get("email") or "").strip().lower()
    if not cid and email_in:
        cid = (_find_vergent_customer_id_by_email(email_in) or "").strip()
    if not cid:
        return _resp(404, {"error": "customer_not_found"})

    cust = _vergent_get_customer(cid)
    v_email = ((cust or {}).get("EmailAddr") or email_in or "").strip().lower()
    if not v_email or "@" not in v_email:
        return _resp(422, {"error": "no_email_on_file"})
    first = ((cust or {}).get("FirstName") or (cust or {}).get("First")
             or (cust or {}).get("FName") or "").strip()

    status = _user_status(v_email)
    already = bool(status) and status not in ("FORCE_CHANGE_PASSWORD", "UNCONFIRMED")

    exp = int(time.time()) + ONBOARD_TTL_DAYS * 86400
    token = _sign_onboard({"cid": cid, "email": v_email, "fn": first, "ln": "", "exp": exp})
    if not token:
        return _resp(500, {"error": "mint_unavailable"})
    url = ALLOWED_ORIGIN.rstrip("/") + "/onboard.html#t=" + token
    log.info("onboard mint-link cid=%s already=%s to=%s", cid, already, _mask_email(v_email))
    return _resp(200, {"url": url, "masked": _mask_email(v_email), "alreadyRegistered": already})


def _onboard_complete(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    p = _verify_onboard((body.get("token") or "").strip())
    if not p:
        return _resp(400, {"error": "invalid_or_expired"})
    password = body.get("password") or ""
    if not _password_ok(password):
        return _resp(400, {"error": "invalid_password"})

    email = (p.get("email") or "").strip().lower()
    vcid = str(p.get("cid") or "").strip()
    first = (p.get("fn") or "").strip()
    last = (p.get("ln") or "").strip()
    if not vcid:
        return _resp(400, {"error": "invalid_token_payload"})

    # Key the account to Vergent's on-file email so creation always satisfies
    # the PreSignUp email-match guard — the token email is only for display, so
    # the link works even if the address we emailed differs slightly from
    # Vergent's record. Fall back to the token email if the lookup is down.
    v_email = _vergent_email_for_cid(vcid)
    if v_email and "@" in v_email:
        email = v_email.lower()
    if not email or "@" not in email:
        return _resp(400, {"error": "invalid_token_payload"})

    status = _user_status(email)
    if status and status not in ("FORCE_CHANGE_PASSWORD", "UNCONFIRMED"):
        # Already fully registered — a magic link must never reset an existing
        # password (that's what /auth/forgot is for). This also makes the link
        # effectively single-use.
        return _resp(409, {"error": "already_registered"})

    if not status:
        attrs = [
            {"Name": "email", "Value": email},
            {"Name": "custom:vergentCustomerId", "Value": vcid},
        ]
        if first:
            attrs.append({"Name": "given_name", "Value": first})
        if last:
            attrs.append({"Name": "family_name", "Value": last})
        try:
            cognito.admin_create_user(
                UserPoolId=USER_POOL_ID, Username=email,
                MessageAction="SUPPRESS", TemporaryPassword=_temp_password(),
                UserAttributes=attrs,
            )
        except ClientError as e:
            cn = e.response.get("Error", {}).get("Code", "")
            if cn != "UsernameExistsException":
                log.warning("onboard create failed: %s", cn)
                return _resp(500, {"error": "signup_failed"})

    try:
        cognito.admin_set_user_password(
            UserPoolId=USER_POOL_ID, Username=email, Password=password, Permanent=True,
        )
        cognito.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID, Username=email,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
    except ClientError as e:
        cn = e.response.get("Error", {}).get("Code", "")
        if cn == "InvalidPasswordException":
            return _resp(400, {"error": "invalid_password"})
        log.warning("onboard set-password failed: %s", cn)
        return _resp(500, {"error": "confirm_failed"})

    # Auto-login: the link already proved email ownership, so issue tokens
    # directly (no second MFA round). If that step fails the account is still
    # set up — the page falls back to the normal login screen.
    tokens, err = _admin_initiate_password_auth(email, password)
    if err or not tokens:
        log.warning("onboard auto-login failed for %s: %s", _mask_email(email), err)
        return _resp(200, {"ok": True, "autoLogin": False})
    return _resp(200, {
        "ok": True,
        "autoLogin": True,
        "idToken": tokens.get("IdToken"),
        "accessToken": tokens.get("AccessToken"),
        "refreshToken": tokens.get("RefreshToken"),
    })


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    # Keep-warm ping (EventBridge schedule) — return immediately.
    if isinstance(event, dict) and event.get("warmup"):
        return {"statusCode": 200, "body": "warm"}
    try:
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or "").upper()
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS, "body": ""}

        path = http.get("path") or event.get("rawPath") or ""
        if path.endswith("/auth/login"):
            return _login(event)
        if path.endswith("/auth/send-code"):
            return _send_code(event)
        if path.endswith("/auth/verify-code"):
            return _verify_code(event)
        if path.endswith("/auth/forgot/start"):
            return _forgot_start(event)
        if path.endswith("/auth/forgot/confirm"):
            return _forgot_confirm(event)
        if path.endswith("/auth/signup/start"):
            return _signup_start(event)
        if path.endswith("/auth/signup/confirm"):
            return _signup_confirm(event)
        if path.endswith("/auth/onboard/verify"):
            return _onboard_verify(event)
        if path.endswith("/auth/onboard/complete"):
            return _onboard_complete(event)
        if path.endswith("/auth/onboard/mint-link"):
            return _onboard_mint_link(event)
        return _resp(404, {"error": "not_found"})
    except Exception as exc:
        log.exception("auth_mfa unexpected error: %s", exc)
        return _resp(500, {"error": "internal_error"})
