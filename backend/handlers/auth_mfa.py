"""
Server-side MFA login flow (email via SES, SMS via Vergent).

Routes (no JWT auth — these ARE the auth endpoints):
  POST /api/auth/login        {email, password}
  POST /api/auth/send-code    {mfaSession, channel}   channel = "email" | "sms"
  POST /api/auth/verify-code  {mfaSession, code}

Delivery channels:
  email  -> SES SendEmail with a 6-digit code we generate ourselves
  sms    -> Vergent POST /api/Communication/RequestPinByText
            (Vergent generates + delivers; we verify via /VerifyPin)
  This sidesteps SNS sandbox and reuses the SMS pipeline Vergent already
  uses to text customers about payment reminders etc.

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
  MFA_EMAIL_SENDER           verified SES sender
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

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
APP_CLIENT_ID = os.environ["COGNITO_APP_CLIENT_ID"]
TABLE = os.environ.get("MFA_SESSION_TABLE", "cif-portal-mfa-sessions-dev")
EMAIL_SENDER = os.environ.get("MFA_EMAIL_SENDER", "lhdcapital@gmail.com")
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

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
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


def _vergent_sms_request_pin(phone_digits: str) -> Tuple[bool, str]:
    """Ask Vergent to generate + send a PIN via SMS. Returns (ok, message)."""
    tok = _get_apim_token()
    if not tok:
        return False, "apim_auth_failed"
    creds = _get_vergent_creds() or {}
    status, body, raw = _http(
        f"{APIM_BASE}/api/Communication/RequestPinByText", "POST",
        body={"phoneNumber": phone_digits, "type": 0, "groupType": 0},
        headers={"x-api-key": creds.get("xApiKey", ""), "Authorization": f"Bearer {tok}"},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("RequestPinByText status=%s body=%s", status, (raw or "")[:200])
        return False, f"vergent_error_{status}"
    if body.get("result") is True:
        return True, "ok"
    return False, body.get("message") or "vergent_declined"


def _vergent_sms_verify_pin(phone_digits: str, pin: str) -> bool:
    tok = _get_apim_token()
    if not tok:
        return False
    creds = _get_vergent_creds() or {}
    status, body, raw = _http(
        f"{APIM_BASE}/api/Communication/VerifyPin", "POST",
        body={"phoneNumber": phone_digits, "pin": pin, "type": 0, "groupType": 0},
        headers={"x-api-key": creds.get("xApiKey", ""), "Authorization": f"Bearer {tok}"},
    )
    if status != 200 or not isinstance(body, dict):
        log.warning("VerifyPin status=%s body=%s", status, (raw or "")[:200])
        return False
    return bool(body.get("result") is True)


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


def _arm_vergent_pin(session_id: str) -> None:
    now = int(time.time())
    ddb.update_item(
        TableName=TABLE, Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET #m = :m, #ch = :ch, attempts = :z, expiresAt = :e REMOVE codeHash",
        ExpressionAttributeNames={"#m": "mode", "#ch": "channel"},
        ExpressionAttributeValues={
            ":m": {"S": "vergent_pin"},
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
# Senders
# ─────────────────────────────────────────
def _send_email(to: str, code: str) -> bool:
    body_text = (
        f"Cash in Flash — Sign-in code\n\n"
        f"Your sign-in code is: {code}\n\n"
        f"Didn't try to sign in? You can ignore this email. If you think "
        f"someone is trying to access your account, reset your password at "
        f"https://portal.cashinflash.com/forgot.html.\n\n"
        f"Please do not share this code with anyone. A Cash in Flash Representative "
        f"will NEVER ask you to provide them with your sign-in code.\n\n"
        f"Questions? Call our Customer Service Team at (747) 270-7121.\n\n"
        f"---\n"
        f"This email message contains information from Cash in Flash and is confidential. "
        f"If you received this email in error, please notify us at (747) 270-7121 or "
        f"support@cashinflash.com.\n\n"
        f"© 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.\n"
        f"Cash in Flash, 13937B Van Nuys Blvd, Arleta, CA 91331"
    )
    body_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;overflow:hidden;">
        <tr><td align="center" style="background:#1e3a2f;padding:44px 24px;">
          <img src="https://d1zucrj1ouu3c.cloudfront.net/images/white_logo_350.png" alt="Cash in Flash" width="210" style="display:block;max-width:210px;width:210px;height:auto;border:0;">
        </td></tr>
        <tr><td style="padding:36px 40px 20px;">
          <h1 style="margin:0 0 16px;font-size:21px;font-weight:700;color:#0E8741;line-height:1.25;">Your sign-in code is: {code}</h1>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Didn't try to sign in? Please <a href="https://d1zucrj1ouu3c.cloudfront.net/forgot.html" style="color:#0E8741;text-decoration:underline;">reset your password</a>.</p>
          <p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#1a1a2e;">Please do not provide this code to anyone. A Cash in Flash Representative will <strong>never</strong> ask you to provide them with your sign-in code.</p>
          <p style="margin:0 0 4px;font-size:14px;line-height:1.55;color:#1a1a2e;">If you still have questions, contact our Customer Service Team at <a href="tel:+17472707121" style="color:#1a1a2e;font-weight:600;text-decoration:underline;">(747) 270-7121</a>.</p>
        </td></tr>
        <tr><td style="padding:22px 40px 34px;color:#6b7280;font-size:11px;line-height:1.6;">
          <p style="margin:0 0 10px;">This email message contains information from Cash in Flash and is confidential. The included information is intended only for the use of the individual or entity named above. If you are not the intended recipient, be aware that any disclosure, copying, distribution, or use of the contents of this message is prohibited.</p>
          <p style="margin:0 0 10px;">If you received this email in error, please notify us immediately by telephone at <a href="tel:+17472707121" style="color:#6b7280;text-decoration:underline;">(747) 270-7121</a> or email at <a href="mailto:support@cashinflash.com" style="color:#6b7280;text-decoration:underline;">support@cashinflash.com</a>.</p>
          <p style="margin:0 0 10px;">&copy; 2026 Dhan Corporation d/b/a Cash in Flash. All Rights Reserved. License #214840.</p>
          <p style="margin:0 0 4px;">This email was sent by Cash in Flash<br>13937B Van Nuys Blvd, Arleta, CA 91331</p>
          <p style="margin:10px 0 0;"><a href="https://cashinflash.com/privacy/" style="color:#0E8741;text-decoration:underline;">Privacy Policy</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    try:
        ses.send_email(
            Source=EMAIL_SENDER,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": "Your Cash in Flash sign-in code", "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        return True
    except ClientError as e:
        err_code = e.response.get("Error", {}).get("Code")
        log.error("SES send_email failed: %s", err_code)
        return False


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
    if not tokens:
        log.info("login failed for %s: %s", _mask_email(email), err)
        return _resp(401, {"error": "invalid_credentials"})

    user = _admin_get_user(email)
    sub = user.get("Attrs", {}).get("sub", "")
    vergent_cid = user.get("Attrs", {}).get("custom:vergentCustomerId")

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

    channels = [{"key": "email", "label": "Email", "target": _mask_email(email)}]
    # SMS is temporarily disabled — Vergent's Communication/RequestPinByText endpoint
    # returns SKIP for generic OTP (it's only wired for marketing opt-in flows).
    # Will re-enable once we stand up Twilio or get SNS production access.
    if phone_digits and os.environ.get("MFA_SMS_ENABLED") == "1":
        channels.append({"key": "sms", "label": "Text message", "target": _mask_phone(phone_digits)})

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
        if not _send_email(s["email"], code):
            return _resp(502, {"error": "delivery_failed_email"})
        return _resp(200, {"ok": True, "channel": "email", "expiresInSec": CODE_TTL})

    # channel == sms
    phone = s.get("phone")
    if not phone:
        return _resp(400, {"error": "no_phone_on_file"})
    ok, msg = _vergent_sms_request_pin(phone)
    if not ok:
        log.warning("vergent sms request failed: %s", msg)
        return _resp(502, {"error": "delivery_failed_sms", "detail": msg})
    _arm_vergent_pin(session_id)
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
    ok = False
    if mode == "our_code":
        ok = hmac.compare_digest(_hash_code(code), s.get("codeHash") or "")
    elif mode == "vergent_pin":
        phone = s.get("phone") or ""
        ok = _vergent_sms_verify_pin(phone, code)
    else:
        # Code never sent — session armed but nothing to verify.
        return _resp(400, {"error": "no_code_sent"})

    if not ok:
        attempts = s["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            _delete_session(session_id)
            return _resp(401, {"error": "too_many_attempts"})
        _bump_attempts(session_id, attempts)
        return _resp(401, {"error": "invalid_code", "attemptsRemaining": MAX_ATTEMPTS - attempts})

    tokens = s["tokens"]
    _delete_session(session_id)
    return _resp(200, {
        "idToken": tokens.get("IdToken"),
        "accessToken": tokens.get("AccessToken"),
        "refreshToken": tokens.get("RefreshToken"),
        "expiresIn": tokens.get("ExpiresIn") or 3600,
    })


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
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
        return _resp(404, {"error": "not_found"})
    except Exception as exc:
        log.exception("auth_mfa unexpected error: %s", exc)
        return _resp(500, {"error": "internal_error"})
