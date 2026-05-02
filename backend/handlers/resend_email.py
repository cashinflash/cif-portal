"""Resend email client — stdlib only (urllib).

Replaces our former AWS SES `send_email` calls (login MFA codes,
admin change-request notifications, customer change-request
confirmations). AWS denied SES production access twice citing
"could have a negative impact on our service" — pivoted to Resend
which only required ~5 min of DNS work (SPF + DKIM merged with
existing Google Workspace records on cashinflash.com).

Secret fields (at RESEND_SECRET_ARN):
  apiKey        re_xxxxxxxx       — full API key from dashboard.resend.com
  fromAddress   no-reply@cashinflash.com  — verified sender

API: https://resend.com/docs/api-reference/emails/send-email
  POST https://api.resend.com/emails
  Authorization: Bearer <apiKey>
  Body: { from, to, subject, text, html, reply_to }
  Response 200/202: { id: "..." }
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()

_secrets = boto3.client(
    "secretsmanager",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
_creds_cache: Optional[dict] = None

API_URL = "https://api.resend.com/emails"
DEFAULT_REPLY_TO = "info@cashinflash.com"


def _load_creds() -> Optional[dict]:
    """Fetch + cache {apiKey, fromAddress} from Secrets Manager."""
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    arn = os.environ.get("RESEND_SECRET_ARN") or ""
    if not arn:
        log.warning("RESEND_SECRET_ARN not set")
        return None
    try:
        resp = _secrets.get_secret_value(SecretId=arn)
    except ClientError as e:
        log.warning("resend secret read failed: %s",
                    e.response.get("Error", {}).get("Code"))
        return None
    p = json.loads(resp["SecretString"])
    api_key = p.get("apiKey") or p.get("api_key")
    from_addr = p.get("fromAddress") or p.get("from_address") or p.get("from")
    if not (api_key and from_addr):
        log.warning("resend secret missing fields apiKey=%s fromAddress=%s",
                    bool(api_key), bool(from_addr))
        return None
    _creds_cache = {"apiKey": api_key, "fromAddress": from_addr}
    return _creds_cache


def send(*, to: str, subject: str, html: str = "", text: str = "",
         reply_to: str = DEFAULT_REPLY_TO,
         timeout: int = 10) -> Tuple[bool, Optional[str], Optional[str]]:
    """Send a transactional email via Resend.

    Returns (ok, error_code, error_message). On success error_code and
    error_message are both None. On failure error_code is a short
    machine code (e.g. http_429, network, validation_error) and
    error_message is the human-readable detail.
    """
    creds = _load_creds()
    if not creds:
        return False, "creds_missing", "Resend secret not configured"
    if not to or "@" not in to:
        return False, "bad_recipient", f"invalid to address: {to!r}"
    if not (html or text):
        return False, "empty_body", "must provide html or text"

    payload: dict = {
        "from": creds["fromAddress"],
        "to": [to],
        "subject": subject,
    }
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL, method="POST", data=data,
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
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
            msg_id = body.get("id") if isinstance(body, dict) else None
            log.info("resend send ok to=%s id=%s", _mask(to), msg_id or "?")
            return True, None, None
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
        # Resend errors: { name: "validation_error", message: "..." } or similar
        err_name = body.get("name") if isinstance(body, dict) else None
        err_msg = body.get("message") if isinstance(body, dict) else None
        code = err_name or f"http_{e.code}"
        log.warning("resend send failed http=%s code=%s msg=%s to=%s",
                    e.code, code, (err_msg or raw)[:200], _mask(to))
        return False, code, (err_msg or raw)[:300]
    except Exception as e:
        log.exception("resend send unexpected to=%s: %s", _mask(to), e)
        return False, "network", str(e)[:200]


def _mask(addr: str) -> str:
    if not addr or "@" not in addr:
        return "***"
    name, _, dom = addr.partition("@")
    if len(name) <= 2:
        return "***@" + dom
    return name[0] + "***" + name[-1] + "@" + dom
