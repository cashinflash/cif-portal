"""Telnyx Verify client — stdlib only (urllib).

Verify is Telnyx's turnkey OTP service:
  - POST /v2/verifications/sms                                            -> start
  - POST /v2/verifications/by_phone_number/{phone}/actions/verify         -> check

Telnyx generates the code, sends it from the configured Verify Profile
(which references our messaging profile + toll-free number), and validates
on submit. We just record "this phone is in a verify session" in DDB so
/verify-code knows where to route the submitted code.

Secret fields (at TELNYX_SECRET_ARN):
  apiKey            -> KEY...
  verifyProfileId   -> UUID from Mission Control → Verify → Verify Profiles
"""
from __future__ import annotations

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

BASE = "https://api.telnyx.com/v2"


def _load_creds() -> Optional[dict]:
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    arn = os.environ.get("TELNYX_SECRET_ARN") or ""
    if not arn:
        log.warning("TELNYX_SECRET_ARN not set")
        return None
    try:
        resp = _secrets.get_secret_value(SecretId=arn)
    except ClientError as e:
        log.warning("telnyx secret read failed: %s", e.response.get("Error", {}).get("Code"))
        return None
    p = json.loads(resp["SecretString"])
    api_key = p.get("apiKey") or p.get("api_key")
    profile = p.get("verifyProfileId") or p.get("verify_profile_id")
    if not (api_key and profile):
        log.warning("telnyx secret missing fields apiKey=%s verifyProfileId=%s",
                    bool(api_key), bool(profile))
        return None
    _creds_cache = {"apiKey": api_key, "verifyProfileId": profile}
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


def _post(creds: dict, path: str, body: dict, timeout: int = 10) -> Tuple[int, dict, str]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, method="POST", data=data,
        headers={
            "Authorization": f"Bearer {creds['apiKey']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "cif-portal/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace") or "{}"
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {}
            return r.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = (e.read() or b"").decode("utf-8", "replace")
        except Exception:
            pass
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return e.code, parsed, raw
    except Exception as e:
        log.error("telnyx verify %s network: %s", path, e)
        return 0, {}, str(e)[:200]


def _first_error_detail(body: dict) -> str:
    errs = body.get("errors") or []
    if isinstance(errs, list) and errs:
        e0 = errs[0] or {}
        return f"{e0.get('code', '?')}:{e0.get('title', e0.get('detail', ''))}"
    return ""


def start_sms(to: str) -> Tuple[bool, str]:
    """Fire off a Verify verification. Telnyx generates the code and texts it
    from our toll-free number. Returns (ok, detail) where detail is the
    verification ID on success or a short error string on failure."""
    creds = _load_creds()
    if not creds:
        return False, "telnyx_verify_creds_missing"
    to_e164 = _normalize_e164(to)
    if not to_e164:
        return False, "bad_to_number"

    status, body, _raw = _post(
        creds, "/verifications/sms",
        {"phone_number": to_e164, "verify_profile_id": creds["verifyProfileId"], "code_length": 6},
    )
    data = body.get("data") if isinstance(body, dict) else None
    if status in (200, 201) and isinstance(data, dict):
        log.info("verify start ok to=%s id=%s", _mask(to_e164), data.get("id", ""))
        return True, data.get("id", "")

    detail = _first_error_detail(body) or f"http_{status}"
    log.warning("verify start failed http=%s detail=%s", status, detail)
    return False, f"telnyx_{detail}"


def check(to: str, code: str) -> Tuple[bool, str]:
    """Ask Telnyx to verify the submitted code for this phone.

    Returns (approved, status_str) where status_str is:
      "approved" -> accepted by Telnyx
      "pending"  -> wrong code (still in window)
      "expired"  -> no active verification (404 from Telnyx)
      "telnyx_<detail>" -> other failure
    """
    creds = _load_creds()
    if not creds:
        return False, "telnyx_verify_creds_missing"
    to_e164 = _normalize_e164(to)
    if not to_e164:
        return False, "bad_to_number"

    encoded = urllib.parse.quote(to_e164, safe="")
    status, body, _raw = _post(
        creds, f"/verifications/by_phone_number/{encoded}/actions/verify",
        {"code": code, "verify_profile_id": creds["verifyProfileId"]},
    )

    if status == 404:
        return False, "expired"

    data = body.get("data") if isinstance(body, dict) else None
    if status in (200, 201) and isinstance(data, dict):
        rc = (data.get("response_code") or "").lower()
        if rc == "accepted":
            return True, "approved"
        if rc == "rejected":
            return False, "pending"
        return False, rc or "unknown"

    detail = _first_error_detail(body) or f"http_{status}"
    log.warning("verify check failed http=%s detail=%s", status, detail)
    return False, f"telnyx_{detail}"


def _mask(phone: str) -> str:
    if not phone:
        return "***"
    return f"{phone[:3]}***{phone[-4:]}" if len(phone) >= 7 else "***"
