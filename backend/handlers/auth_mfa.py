"""
Server-side MFA login flow.

Three routes (no JWT auth — these ARE the auth endpoints):
  POST /api/auth/login        {email, password}
  POST /api/auth/send-code    {mfaSession, channel}
  POST /api/auth/verify-code  {mfaSession, code}

Flow:
  1. Client POSTs /login with email+password.
  2. Lambda calls AdminInitiateAuth(ADMIN_USER_PASSWORD_AUTH).
     - On success it gets Cognito tokens but DOES NOT return them to the client.
     - It generates a 6-digit code, stores {tokens, code_hash, attempts, channel}
       in DynamoDB (cif-portal-mfa-sessions-dev) keyed by a random sessionId,
       with a 5-minute TTL.
     - It sends the code via the user's verified email by default.
     - Returns {mfaSession, channels:[{key,label,target}], expiresInSec}.
  3. Client renders the channel-pick UI. If user picks SMS, client calls
     /send-code with the new channel — Lambda regenerates the code and
     sends it via SNS Publish to the user's phone_number attribute.
  4. Client renders code-entry UI. User submits → /verify-code.
     Lambda compares (constant-time), and on match returns the Cognito
     tokens that were stashed at step 2. The frontend stores them in
     sessionStorage exactly the same way the old USER_PASSWORD_AUTH flow did.

Security model:
  - Cognito tokens never leave the Lambda environment until MFA passes.
  - Code stored only as sha256(code).
  - 3 wrong attempts → session deleted, client must re-login.
  - 5-minute TTL enforced both in DynamoDB and in the handler.
  - The MFA session id is a 256-bit secret; effectively unguessable.

Environment:
  COGNITO_USER_POOL_ID       us-east-1_U508xOs95
  COGNITO_APP_CLIENT_ID      1mddi61n19hftaldt9t3r622b
  MFA_SESSION_TABLE          cif-portal-mfa-sessions-dev
  MFA_EMAIL_SENDER           verified SES sender (e.g. lhdcapital@gmail.com today)
  MFA_CODE_TTL_SECS          default 300

IAM:
  cognito-idp:AdminInitiateAuth, AdminGetUser on the pool
  dynamodb:PutItem, GetItem, DeleteItem on the MFA sessions table
  ses:SendEmail (any verified sender)
  sns:Publish (any phone — sandbox lifted prereq for prod)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
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

cognito = boto3.client("cognito-idp")
ddb = boto3.client("dynamodb")
ses = boto3.client("ses")
sns = boto3.client("sns")

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
    # Six digits, leading zeros allowed.
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


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) >= 4:
        return f"***-***-{digits[-4:]}"
    return ""


def _admin_get_user(username: str) -> Dict[str, Any]:
    try:
        u = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=username)
    except ClientError as e:
        log.warning("admin_get_user failed: %s", e.response.get("Error", {}).get("Code"))
        return {}
    attrs = {a["Name"]: a["Value"] for a in u.get("UserAttributes", [])}
    return {"Username": u.get("Username"), "Attrs": attrs, "Status": u.get("UserStatus")}


def _admin_initiate_password_auth(email: str, password: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Returns (auth_result, error_code). auth_result has IdToken/AccessToken/RefreshToken."""
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
        # The pool might require challenge response we don't handle here (e.g. NEW_PASSWORD_REQUIRED).
        return None, r.get("ChallengeName") or "ChallengeRequired"
    return {
        "IdToken": ar.get("IdToken"),
        "AccessToken": ar.get("AccessToken"),
        "RefreshToken": ar.get("RefreshToken"),
        "ExpiresIn": ar.get("ExpiresIn"),
    }, None


def _store_session(session_id: str, *, email: str, sub: str, code_hash: str,
                   tokens: Dict[str, str], channel: str, phone: Optional[str]) -> None:
    now = int(time.time())
    item = {
        "sessionId": {"S": session_id},
        "createdAt": {"N": str(now)},
        "expiresAt": {"N": str(now + CODE_TTL)},
        "email": {"S": email},
        "sub": {"S": sub},
        "codeHash": {"S": code_hash},
        "channel": {"S": channel},
        "attempts": {"N": "0"},
        "tokens": {"S": json.dumps(tokens)},
    }
    if phone:
        item["phone"] = {"S": phone}
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
        "sub": item["sub"]["S"],
        "codeHash": item["codeHash"]["S"],
        "channel": item["channel"]["S"],
        "attempts": int(item["attempts"]["N"]),
        "tokens": json.loads(item["tokens"]["S"]),
        "phone": item.get("phone", {}).get("S"),
        "expiresAt": int(item["expiresAt"]["N"]),
    }


def _bump_attempts(session_id: str, attempts: int) -> None:
    ddb.update_item(
        TableName=TABLE,
        Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET attempts = :a",
        ExpressionAttributeValues={":a": {"N": str(attempts)}},
    )


def _delete_session(session_id: str) -> None:
    try:
        ddb.delete_item(TableName=TABLE, Key={"sessionId": {"S": session_id}})
    except ClientError:
        pass


def _rotate_code(session_id: str, code_hash: str, channel: str) -> None:
    now = int(time.time())
    ddb.update_item(
        TableName=TABLE,
        Key={"sessionId": {"S": session_id}},
        UpdateExpression="SET codeHash = :c, channel = :ch, attempts = :z, expiresAt = :e",
        ExpressionAttributeValues={
            ":c": {"S": code_hash},
            ":ch": {"S": channel},
            ":z": {"N": "0"},
            ":e": {"N": str(now + CODE_TTL)},
        },
    )


def _send_email(to: str, code: str) -> bool:
    body_text = (
        f"Hi,\n\nYour Cash in Flash sign-in code is: {code}\n\n"
        f"This code expires in 5 minutes. If you didn't try to sign in, ignore this email.\n\n"
        f"— Cash in Flash"
    )
    body_html = (
        f"<p>Hi,</p>"
        f"<p>Your Cash in Flash sign-in code is: <strong style='font-size:20px;letter-spacing:2px'>{code}</strong></p>"
        f"<p style='color:#666;font-size:14px'>This code expires in 5 minutes. If you didn't try to sign in, ignore this email.</p>"
        f"<p style='color:#0E8741;font-weight:600'>— Cash in Flash</p>"
    )
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
        log.error("SES send_email failed: %s", e.response.get("Error", {}).get("Code"))
        return False


def _send_sms(phone: str, code: str) -> bool:
    msg = f"Cash in Flash sign-in code: {code}. Expires in 5 minutes."
    try:
        sns.publish(
            PhoneNumber=phone,
            Message=msg,
            MessageAttributes={
                "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
                "AWS.SNS.SMS.SenderID": {"DataType": "String", "StringValue": "CashFlash"},
            },
        )
        return True
    except ClientError as e:
        log.error("SNS publish failed: %s", e.response.get("Error", {}).get("Code"))
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
        # Generic message to avoid user enumeration
        log.info("login failed for %s: %s", _mask_email(email), err)
        return _resp(401, {"error": "invalid_credentials"})

    user = _admin_get_user(email)
    sub = user.get("Attrs", {}).get("sub", "")
    phone = user.get("Attrs", {}).get("phone_number") or None

    code = _new_code()
    code_hash = _hash_code(code)
    session_id = _new_session_id()
    _store_session(
        session_id,
        email=email,
        sub=sub,
        code_hash=code_hash,
        tokens=tokens,
        channel="email",
        phone=phone,
    )

    if not _send_email(email, code):
        # Don't fail the whole flow — let the client try resend or pick SMS.
        log.warning("Default email send failed for %s; client may resend", _mask_email(email))

    channels = [{"key": "email", "label": "Email", "target": _mask_email(email)}]
    if phone:
        channels.append({"key": "sms", "label": "Text message", "target": _mask_phone(phone)})

    return _resp(200, {
        "mfaSession": session_id,
        "channels": channels,
        "deliveredTo": "email",
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
    if channel == "sms" and not s.get("phone"):
        return _resp(400, {"error": "no_phone_on_file"})

    code = _new_code()
    code_hash = _hash_code(code)
    _rotate_code(session_id, code_hash, channel)

    sent = (_send_email(s["email"], code) if channel == "email"
            else _send_sms(s["phone"], code))
    if not sent:
        return _resp(502, {"error": "delivery_failed"})

    return _resp(200, {
        "ok": True,
        "channel": channel,
        "expiresInSec": CODE_TTL,
    })


def _verify_code(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse(event)
    session_id = body.get("mfaSession") or ""
    code = (body.get("code") or "").strip()
    if not session_id or not code:
        return _resp(400, {"error": "missing_fields"})

    s = _load_session(session_id)
    if not s:
        return _resp(401, {"error": "session_expired"})

    submitted_hash = _hash_code(code)
    if not hmac.compare_digest(submitted_hash, s["codeHash"]):
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
