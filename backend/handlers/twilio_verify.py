"""Twilio Verify client — stdlib only (urllib + base64).

Verify is Twilio's turnkey OTP service:
  - POST /v2/Services/{sid}/Verifications       -> start (generate + send code)
  - POST /v2/Services/{sid}/VerificationCheck   -> check submitted code

We don't store codes; Twilio does. Our flow just records "this phone is
in a verify session" in DDB so we know which channel to route the
follow-up /verify-code call to.

Secret fields (at TWILIO_SECRET_ARN):
  accountSid        -> AC...
  authToken         -> ...
  verifyServiceSid  -> VA...   (from Twilio Console → Verify → Services)
  fromNumber        -> unused by Verify (Twilio picks from its pool), but
                       still stored in the secret for the raw Messages
                       path in twilio_sms.py.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()

_secrets = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_creds_cache: Optional[dict] = None

BASE = "https://verify.twilio.com/v2"


def _load_creds() -> Optional[dict]:
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    arn = os.environ.get("TWILIO_SECRET_ARN") or ""
    if not arn:
        log.warning("TWILIO_SECRET_ARN not set")
        return None
    try:
        resp = _secrets.get_secret_value(SecretId=arn)
    except ClientError as e:
        log.warning("twilio secret read failed: %s", e.response.get("Error", {}).get("Code"))
        return None
    p = json.loads(resp["SecretString"])
    sid = p.get("accountSid") or p.get("account_sid")
    tok = p.get("authToken")  or p.get("auth_token")
    svc = p.get("verifyServiceSid") or p.get("verify_service_sid")
    if not (sid and tok and svc):
        log.warning("twilio secret missing fields sid=%s tok=%s svc=%s",
                    bool(sid), bool(tok), bool(svc))
        return None
    _creds_cache = {"accountSid": sid, "authToken": tok, "serviceSid": svc}
    return _creds_cache


def _normalize_e164(number: str) -> Optional[str]:
    digits = "".join(c for c in (number or "") if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if number and number.startswith("+") and 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def _post(creds: dict, path: str, form: dict, timeout: int = 10) -> Tuple[int, dict, str]:
    url = f"{BASE}{path}"
    data = urllib.parse.urlencode(form).encode("utf-8")
    auth = base64.b64encode(f"{creds['accountSid']}:{creds['authToken']}".encode()).decode()
    req = urllib.request.Request(
        url, method="POST", data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "cif-portal/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return r.status, body, ""
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = (e.read() or b"").decode("utf-8", "replace")
        except Exception:
            pass
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}
        return e.code, body, raw
    except Exception as e:
        log.error("twilio verify %s network: %s", path, e)
        return 0, {}, str(e)[:200]


def start_sms(to: str) -> Tuple[bool, str]:
    """Fire off a Verify verification. Twilio picks the sending number from its
    compliant pool, generates a 6-digit code, and texts it.

    Returns (ok, detail). detail is the verification SID on success, a short
    error string on failure.
    """
    creds = _load_creds()
    if not creds:
        return False, "twilio_verify_creds_missing"
    to_e164 = _normalize_e164(to)
    if not to_e164:
        return False, "bad_to_number"
    status, body, raw = _post(
        creds, f"/Services/{creds['serviceSid']}/Verifications",
        {"To": to_e164, "Channel": "sms"},
    )
    if status in (200, 201) and body.get("status") == "pending":
        log.info("verify start ok to=%s sid=%s", _mask(to_e164), body.get("sid", ""))
        return True, body.get("sid", "")
    code = body.get("code") or status
    msg = body.get("message") or "verify_start_failed"
    log.warning("verify start failed http=%s code=%s msg=%s", status, code, msg)
    return False, f"twilio_{code}"


def check(to: str, code: str) -> Tuple[bool, str]:
    """Ask Twilio to verify the submitted code for this phone.

    Returns (approved, status) where status is Twilio's string:
      "approved"  -> matched
      "pending"   -> wrong code (still in the window; retry)
      "canceled"  -> too many wrong attempts or max age
      "max_attempts_reached" -> locked
    """
    creds = _load_creds()
    if not creds:
        return False, "twilio_verify_creds_missing"
    to_e164 = _normalize_e164(to)
    if not to_e164:
        return False, "bad_to_number"
    status, body, _raw = _post(
        creds, f"/Services/{creds['serviceSid']}/VerificationCheck",
        {"To": to_e164, "Code": code},
    )
    if status in (200, 201):
        verify_status = body.get("status", "unknown")
        approved = bool(body.get("valid") is True) or verify_status == "approved"
        return approved, verify_status
    code_ = body.get("code") or status
    msg = body.get("message") or "verify_check_failed"
    # 404 = no verification in progress for this To (expired or never started)
    if status == 404:
        return False, "expired"
    log.warning("verify check failed http=%s code=%s msg=%s", status, code_, msg)
    return False, f"twilio_{code_}"


def _mask(phone: str) -> str:
    if not phone:
        return "***"
    return f"{phone[:3]}***{phone[-4:]}" if len(phone) >= 7 else "***"
