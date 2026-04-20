"""Minimal Twilio Messages client — stdlib only (urllib + base64).

We don't pull the twilio SDK because (a) it's a multi-MB dep for a single
API call, (b) we already have this pattern for Vergent (see loans.py::_http),
(c) the Messages REST API is stable and trivial.

Usage (from a Lambda handler):

    import twilio_sms
    ok, info = twilio_sms.send(
        to="+12163198388",          # E.164
        body="Your Cash in Flash sign-in code: 123456",
        # Creds + from are resolved from Secrets Manager + env at call time.
    )
    if not ok:
        log.warning("twilio send failed: %s", info)

Secret shape at TWILIO_SECRET_ARN:
    {"accountSid": "AC...", "authToken": "...", "fromNumber": "+1..."}

The sender's from number must be a 10DLC-registered US long code (or a
toll-free / short code) with an active A2P campaign — otherwise Twilio
will reject with 21610 / 21730 etc.
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
    payload = json.loads(resp["SecretString"])
    sid = payload.get("accountSid") or payload.get("account_sid")
    tok = payload.get("authToken")  or payload.get("auth_token")
    frm = payload.get("fromNumber") or payload.get("from_number") or os.environ.get("TWILIO_FROM_NUMBER", "")
    if not (sid and tok and frm):
        log.warning("twilio secret missing fields: sid=%s tok=%s from=%s",
                    bool(sid), bool(tok), bool(frm))
        return None
    _creds_cache = {"accountSid": sid, "authToken": tok, "fromNumber": frm}
    return _creds_cache


def _normalize_e164(number: str) -> Optional[str]:
    """Accepts '2163198388', '12163198388', '+12163198388', '(216) 319-8388'.
    Returns E.164 for a US number, or None if we can't parse."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if number and number.startswith("+") and 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def send(to: str, body: str, *, from_number: Optional[str] = None) -> Tuple[bool, str]:
    """Send a single SMS. Returns (ok, detail).

    detail is the Twilio message SID on success, a short error code on
    failure. Does not raise — callers should decide how to handle
    delivery failures.
    """
    creds = _load_creds()
    if not creds:
        return False, "twilio_creds_missing"

    to_e164 = _normalize_e164(to)
    if not to_e164:
        return False, "bad_to_number"

    sender = from_number or creds["fromNumber"]
    url = f"https://api.twilio.com/2010-04-01/Accounts/{creds['accountSid']}/Messages.json"
    form = urllib.parse.urlencode({
        "To": to_e164,
        "From": sender,
        "Body": body[:1600],  # Twilio per-message cap; they segment beyond 160 chars automatically.
    }).encode("utf-8")

    auth = base64.b64encode(f"{creds['accountSid']}:{creds['authToken']}".encode()).decode()
    req = urllib.request.Request(
        url,
        method="POST",
        data=form,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "cif-portal/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode("utf-8", "replace") or "{}")
            sid = resp.get("sid") or ""
            status = resp.get("status") or "unknown"
            log.info("twilio send ok to=%s sid=%s status=%s", _mask(to_e164), sid, status)
            return True, sid
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = (e.read() or b"").decode("utf-8", "replace")
        except Exception:
            pass
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        code = payload.get("code") or e.code
        msg  = payload.get("message") or "http_error"
        log.warning("twilio send http %s code=%s msg=%s", e.code, code, msg)
        return False, f"twilio_{code}"
    except Exception as e:
        log.error("twilio send network error: %s", e)
        return False, "twilio_network_error"


def _mask(phone: str) -> str:
    if not phone:
        return "***"
    return f"{phone[:3]}***{phone[-4:]}" if len(phone) >= 7 else "***"
