"""POST /api/if/submit — native debit-card disbursement form submissions.

Sits behind the /if page on cashinflash.com (Instant Funding). The
customer enters their card details in a CIF-owned HTML form; the
browser POSTs the JSON here. This Lambda:

    1. Validates the payload shape (Luhn, exp bounds, ZIP shape).
    2. Envelope-encrypts the sensitive fields with KMS. The ciphertext
       is stored in DynamoDB under a UUIDv4 key with a 72-hour TTL.
       Plaintext PAN/CVV exist only in-memory for ~100 ms and are
       never logged.
    3. Emails a notification to the staff inbox with cardholder
       name, last-4, brand, exp, and a deep link to the dashboard
       view. The PAN and CVV are NEVER in the email body.
    4. Returns 200 + submissionId to the browser (no card data
       echoed back).

Companion handler below, GET /api/if/view/{id}, is used by the
internal dashboard to pull the plaintext once for manual entry into
Vergent. It requires a shared-secret header and deletes the record
on first successful read so the PAN can't be viewed twice from the
same link.

Environment:
  IF_KMS_KEY_ID       KMS key ARN or alias used for encryption
  IF_DDB_TABLE        DynamoDB table name for submissions
  IF_NOTIFY_EMAIL     staff inbox for submission notifications
  IF_VIEW_SHARED_SECRET  secret the dashboard sends on GET/view
  IF_VIEW_URL_BASE    e.g. https://app.cashinflash.com/app?if=
                      (submission id is concatenated directly — if
                      your env value needs a / separator, put it in
                      the env value itself)
  MFA_EMAIL_SENDER    verified SES From address (reuses auth-mfa var)
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError

# Layer modules (Vergent v2 APIM client + secrets loader). Used for
# the auto-match step in push_to_vergent — looks up the Vergent
# customer by borrower name so staff don't have to type the ID by
# hand for unambiguous matches.
import vergent  # type: ignore


# ─────────────────────────────────────────
# Globals / clients
# ─────────────────────────────────────────
log = logging.getLogger()
log.setLevel(logging.INFO)

_kms = boto3.client("kms")
_ddb = boto3.client("dynamodb")
_ses = boto3.client("ses")
_secrets = boto3.client("secretsmanager")

IF_KMS_KEY_ID = os.environ.get("IF_KMS_KEY_ID", "alias/cif-portal-if-vault")
IF_DDB_TABLE = os.environ.get("IF_DDB_TABLE", "cif-portal-if-submissions-dev")
IF_NOTIFY_EMAIL = os.environ.get("IF_NOTIFY_EMAIL", "loans@cashinflash.com")
IF_VIEW_SHARED_SECRET = os.environ.get("IF_VIEW_SHARED_SECRET", "")
IF_VIEW_URL_BASE = os.environ.get("IF_VIEW_URL_BASE", "https://app.cashinflash.com/app?if=")
EMAIL_SENDER = os.environ.get("MFA_EMAIL_SENDER", "no-reply@cashinflash.com")

# Repay CardSafe (server-side card tokenization). Reused from
# .github/workflows/store-repay-secrets.yml — Secrets Manager JSON has
# gatewayApiUser, gatewaySecureToken, gatewayMerchantId.
REPAY_SECRET_ARN = os.environ.get("REPAY_SECRET_ARN", "cif-portal/repay/credentials")
CARDSAFE_URL = os.environ.get(
    "CARDSAFE_URL", "https://api.repayonline.com/ws/CardSafe.asmx/StoreCard")

# Vergent v1 (push the tokenized card to the customer record).
VERGENT_CREDS_SECRET = os.environ.get("VERGENT_CREDS_SECRET", "cif-portal/vergent/credentials")
V1_BASE = os.environ.get("VERGENT_V1_BASE_URL", "https://shared.vergentlms.com/api/api").rstrip("/")
VERGENT_COMPANY_ID = int(os.environ.get("VERGENT_COMPANY_ID", "386"))
_V1_TOKEN_TTL = 60 * 60  # one hour

# 30 days. Staff now manually delete records; TTL is the safety net
# so vault records don't accumulate forever if a staff member
# forgets or an application never gets resolved.
TTL_SECONDS = 30 * 24 * 60 * 60

ALLOWED_ORIGIN = os.environ.get(
    "PORTAL_ORIGIN", "https://my.cashinflash.com"
)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-View-Secret",
    "Access-Control-Max-Age": "300",
    "Vary": "Origin",
    "Cache-Control": "no-store",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


# ─────────────────────────────────────────
# Response helpers
# ─────────────────────────────────────────
def _json_response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _cors_preflight() -> Dict[str, Any]:
    return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}


# ─────────────────────────────────────────
# Validation
# ─────────────────────────────────────────
_ZIP_RE = re.compile(r"^\d{5}(-?\d{4})?$")


def _digits(s: Any) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _luhn_ok(digits: str) -> bool:
    if not digits or not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _validate(body: Dict[str, Any]) -> Tuple[bool, str]:
    """Minimal structural checks — we accept whatever the customer types
    and let staff sort out bad data on their end.

    The *only* things that genuinely must hold for the record to be
    usable:
      • borrower + cardholder names are present (staff need a label),
      • a card-number-shaped string is present (≥12 digits),
      • CVV is present (≥3 digits),
      • expiration has MM + YY (we don't gate on whether the date is
        actually in the future — if it's expired, staff will reach out),
      • billing ZIP is non-empty,
      • the legal acknowledgment was checked.

    Previous strict gates (Luhn, future-only exp, 5-/9-digit US ZIP
    regex) caused the form to reject perfectly reasonable cards for
    edge reasons — staff told us to stop blocking here.
    """
    for k in ("BorrowerFirstName", "BorrowerLastName",
              "CardholderFirstName", "CardholderLastName"):
        v = (body.get(k) or "").strip()
        if not v or len(v) > 60:
            return False, f"invalid_{k}"
    pan = _digits(body.get("CardNumber"))
    if len(pan) < 12 or len(pan) > 19:
        return False, "card_invalid"
    cvv = _digits(body.get("CVV"))
    if not (3 <= len(cvv) <= 4):
        return False, "ccv_invalid"
    try:
        mm = int(body.get("ExpMonth") or 0)
        yy = int(body.get("ExpYear") or 0)
    except (TypeError, ValueError):
        return False, "exp_invalid"
    if not (1 <= mm <= 12):
        return False, "exp_invalid"
    if yy < 100:
        yy += 2000
    if yy < 2000 or yy > 2099:
        return False, "exp_invalid"
    if not (body.get("BillingZip") or "").strip():
        return False, "zip_invalid"
    if not body.get("Acknowledged"):
        return False, "ack_required"
    return True, ""


def _detect_brand(digits: str) -> str:
    if not digits:
        return "Other"
    if digits.startswith("4"):
        return "Visa"
    if digits[:2] in {"34", "37"}:
        return "Amex"
    if digits[:2] in {"51", "52", "53", "54", "55"}:
        return "MasterCard"
    if digits[:4].isdigit():
        four = int(digits[:4])
        if 2221 <= four <= 2720:
            return "MasterCard"
    if digits.startswith("6011") or digits[:2] == "65":
        return "Discover"
    if digits[:6].isdigit() and 622126 <= int(digits[:6]) <= 622925:
        return "Discover"
    return "Other"


# ─────────────────────────────────────────
# Crypto
# ─────────────────────────────────────────
def _encrypt(plaintext_blob: bytes, submission_id: str) -> str:
    """KMS-encrypt a bytes blob, return base64-encoded ciphertext.

    The submission id is used as an EncryptionContext so a ciphertext
    can't be decrypted against a different record's id.
    """
    resp = _kms.encrypt(
        KeyId=IF_KMS_KEY_ID,
        Plaintext=plaintext_blob,
        EncryptionContext={"submission_id": submission_id},
    )
    return base64.b64encode(resp["CiphertextBlob"]).decode("ascii")


def _decrypt(ciphertext_b64: str, submission_id: str) -> bytes:
    resp = _kms.decrypt(
        CiphertextBlob=base64.b64decode(ciphertext_b64),
        EncryptionContext={"submission_id": submission_id},
    )
    return resp["Plaintext"]


# ─────────────────────────────────────────
# Repay CardSafe (server-side card tokenization)
# ─────────────────────────────────────────
_repay_creds_cache: Optional[Dict[str, Any]] = None


def _get_repay_creds() -> Optional[Dict[str, Any]]:
    """Read Repay credentials JSON from Secrets Manager (cached per warm
    container). Returns None on any error so callers can degrade
    gracefully without leaking the underlying exception."""
    global _repay_creds_cache
    if _repay_creds_cache is not None:
        return _repay_creds_cache
    try:
        resp = _secrets.get_secret_value(SecretId=REPAY_SECRET_ARN)
        _repay_creds_cache = json.loads(resp["SecretString"])
        return _repay_creds_cache
    except Exception as e:
        log.warning("Repay creds read failed (arn=%s): %s", REPAY_SECRET_ARN, e)
        return None


def _cardsafe_store(*, pan: str, exp_month: int, exp_year: int,
                    cvv: str, name_on_card: str, zip_code: str,
                    customer_key: str) -> Tuple[Optional[str], str]:
    """Tokenize a card via Repay CardSafe StoreCard.

    Returns (token, debug_info). Token is the CardSafe ID we pass to
    Vergent as card_ref. On failure token is None and debug_info
    contains a short diagnostic (status code or exception message)
    suitable for logging — never includes PAN or CVV.

    CardSafe is a SOAP/ASMX web service that also accepts plain
    HTTP POST with form-encoded params. Using the latter so we don't
    have to hand-roll a SOAP envelope.
    """
    creds = _get_repay_creds()
    if not creds:
        return None, "no_creds"
    user = creds.get("gatewayApiUser") or ""
    pwd = creds.get("gatewaySecureToken") or ""
    if not (user and pwd):
        return None, "creds_incomplete"

    # CardSafe expects ExpDate as MMYY (4 digits, no slash).
    exp_str = f"{exp_month:02d}{str(exp_year)[-2:]}"

    form = urlencode({
        "UserName": user,
        "Password": pwd,
        "TokenMode": "Default",
        "CardNum": pan,
        "ExpDate": exp_str,
        "CustomerKey": str(customer_key or ""),
        "NameOnCard": name_on_card or "",
        "Street": "",
        "Zip": zip_code or "",
        "ExtData": "",
    }).encode("utf-8")

    req = Request(
        CARDSAFE_URL,
        data=form,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/xml,application/xml",
        },
    )
    try:
        with urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
            status = r.getcode()
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        log.warning("CardSafe StoreCard HTTP %s: %s", e.code, body[:300])
        return None, f"http_{e.code}"
    except URLError as e:
        log.warning("CardSafe StoreCard URLError: %s", e)
        return None, f"url_error:{e}"

    log.info("CardSafe StoreCard status=%s len=%d preview=%s",
             status, len(raw), raw[:200].replace("\n", " "))

    # ASMX returns XML wrapped in a top-level <string xmlns="..."> when
    # the operation returns a string, OR a structured response with
    # nested elements. Walk the tree and look for token-shaped fields.
    token = _extract_cardsafe_token(raw)
    if not token:
        log.warning("CardSafe StoreCard returned no token: %s", raw[:400].replace("\n", " "))
        return None, "no_token"
    return token, "ok"


def _extract_cardsafe_token(raw: str) -> Optional[str]:
    """Pull a token-looking field out of CardSafe's XML response.

    Repay's docs show several possible response shapes; we look at
    every element and return the first plausible token value. Heuristic:
    any non-empty text in a field whose tag name suggests an id/token
    and which is at least 6 chars and looks token-shaped.
    """
    if not raw or not raw.strip():
        return None
    # Some ASMX endpoints return raw XML (e.g. <string>...</string>);
    # others return a full SOAP envelope. Try parsing both.
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None

    candidates = ("cardsafeid", "token", "cardtoken", "cardid",
                  "cardsafe_id", "card_id", "result", "id")
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1].lower() if "}" in elem.tag else elem.tag.lower()
        if tag not in candidates:
            continue
        val = (elem.text or "").strip()
        if not val:
            continue
        # If the response packs an inner XML doc inside <string>...
        # try parsing once more.
        if val.startswith("<"):
            try:
                inner = ET.fromstring(val)
                for sub in inner.iter():
                    sub_tag = sub.tag.split("}", 1)[-1].lower() if "}" in sub.tag else sub.tag.lower()
                    if sub_tag in candidates and sub.text and sub.text.strip():
                        cand = sub.text.strip()
                        if _looks_like_token(cand):
                            return cand
            except ET.ParseError:
                pass
            continue
        if _looks_like_token(val):
            return val
    return None


def _looks_like_token(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 6:
        return False
    # CardSafe tokens look like alphanumeric / hex / GUID; reject
    # things that are obviously plain words or status codes.
    return bool(re.match(r"^[A-Za-z0-9\-]+$", s)) and s.lower() not in ("success", "ok", "true", "false")


# ─────────────────────────────────────────
# Vergent v1 (push the tokenized card to the customer record)
# ─────────────────────────────────────────
_vergent_creds_cache: Optional[Dict[str, Any]] = None
_v1_token: Optional[str] = None
_v1_token_exp: float = 0.0


def _get_vergent_creds() -> Optional[Dict[str, Any]]:
    global _vergent_creds_cache
    if _vergent_creds_cache is not None:
        return _vergent_creds_cache
    try:
        resp = _secrets.get_secret_value(SecretId=VERGENT_CREDS_SECRET)
        _vergent_creds_cache = json.loads(resp["SecretString"])
        return _vergent_creds_cache
    except Exception as e:
        log.warning("Vergent creds read failed (arn=%s): %s", VERGENT_CREDS_SECRET, e)
        return None


def _get_v1_token() -> Optional[str]:
    global _v1_token, _v1_token_exp
    if _v1_token and time.time() < _v1_token_exp:
        return _v1_token
    creds = _get_vergent_creds()
    if not creds:
        return None
    body = json.dumps({
        "LogonName": creds.get("logonName") or "",
        "Password": creds.get("password") or "",
    }).encode("utf-8")
    req = Request(
        f"{V1_BASE}/authenticate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError, ValueError) as e:
        log.warning("v1 authenticate failed: %s", e)
        return None
    tok = data.get("Token") or data.get("token")
    if not tok:
        log.warning("v1 authenticate returned no Token: %s", str(data)[:200])
        return None
    _v1_token = tok
    _v1_token_exp = time.time() + _V1_TOKEN_TTL
    return tok


def _v1_request(method: str, path: str,
                body: Optional[Dict[str, Any]] = None
                ) -> Tuple[int, Optional[Any], str]:
    """Generic Vergent v1 caller. Returns (status, parsed_body, raw)."""
    tok = _get_v1_token()
    if not tok:
        return 0, None, "no_token"
    url = f"{V1_BASE}{path}"
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Token": tok, "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, method=method, headers=headers)
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="replace")
            status = r.getcode()
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        status = e.code
    except URLError as e:
        return 0, None, f"url_error:{e}"
    parsed: Optional[Any] = None
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
    return status, parsed, raw


# ─────────────────────────────────────────
# Notification email
# ─────────────────────────────────────────
def _send_staff_notification(submission_id: str,
                             meta: Dict[str, Any]) -> None:
    # Concatenate directly — the env value carries its own separator
    # (either a trailing slash for path-style or '?if=' for query
    # style). Keeps us flexible if the dashboard URL scheme changes.
    view_url = f"{IF_VIEW_URL_BASE}{submission_id}"
    text_body = (
        f"Cash in Flash — new debit card submission\n\n"
        f"Borrower:  {meta['borrower_name']}\n"
        f"Cardholder: {meta['cardholder_name']}\n"
        f"Brand:      {meta['brand']}\n"
        f"Last 4:    •••• {meta['last4']}\n"
        f"Exp:       {meta['exp_month']:02d}/{meta['exp_year']}\n"
        f"Zip:       {meta['zip']}\n"
        f"Submitted: {meta['submitted_at']}\n"
        f"ID:        {submission_id}\n\n"
        f"View the full card details to process this submission:\n"
        f"{view_url}\n\n"
        f"For your security, the card number and CVV are NOT in this\n"
        f"email. Click the link above and log in to the staff dashboard.\n"
        f"The record will auto-delete 72 hours from submission time.\n"
    )
    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a2e;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;padding:24px 12px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#ffffff;">
        <tr><td style="background:#0E8741;padding:24px 28px;color:#fff;">
          <p style="margin:0;font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;opacity:.85;">New Submission</p>
          <h1 style="margin:4px 0 0;font-size:1.3rem;font-weight:700;">Debit card submitted for funding</h1>
        </td></tr>
        <tr><td style="padding:28px;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Borrower</td><td style="padding:8px 0;text-align:right;font-weight:600;">{meta['borrower_name']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Cardholder</td><td style="padding:8px 0;text-align:right;font-weight:600;">{meta['cardholder_name']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Brand</td><td style="padding:8px 0;text-align:right;font-weight:600;">{meta['brand']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Last 4</td><td style="padding:8px 0;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;">•••• {meta['last4']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Expiration</td><td style="padding:8px 0;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;">{meta['exp_month']:02d}/{meta['exp_year']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Billing ZIP</td><td style="padding:8px 0;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;">{meta['zip']}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;font-size:.82rem;">Submission ID</td><td style="padding:8px 0;text-align:right;font-family:monospace;font-size:.78rem;color:#6b7280;">{submission_id}</td></tr>
          </table>
          <div style="text-align:center;margin:24px 0 8px;">
            <a href="{view_url}" style="display:inline-block;background:#0E8741;color:#fff;padding:12px 22px;border-radius:8px;font-weight:600;text-decoration:none;">View full card details</a>
          </div>
          <p style="margin:18px 0 0;color:#6b7280;font-size:.82rem;line-height:1.55;">The card number and CVV are not included in this email for security. The record will auto-delete 72 hours after submission if not processed.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    try:
        _ses.send_email(
            Source=EMAIL_SENDER,
            Destination={"ToAddresses": [IF_NOTIFY_EMAIL]},
            Message={
                "Subject": {
                    "Data": f"New IF submission — {meta['borrower_name']} ({meta['brand']} •••• {meta['last4']})",
                    "Charset": "UTF-8",
                },
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
    except ClientError as e:
        err = e.response.get("Error", {}) if hasattr(e, "response") else {}
        log.error(
            "IF notification email failed: to=%s code=%s msg=%s",
            IF_NOTIFY_EMAIL, err.get("Code"), err.get("Message"),
        )


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def submit(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    ok, err = _validate(body)
    if not ok:
        return _json_response(400, {"error": err})

    pan = _digits(body["CardNumber"])
    cvv = _digits(body["CVV"])
    last4 = pan[-4:]
    brand = (body.get("CardType") or _detect_brand(pan))
    exp_month = int(body["ExpMonth"])
    exp_year = int(body["ExpYear"])
    if exp_year < 100:
        exp_year += 2000

    borrower_first = body["BorrowerFirstName"].strip()
    borrower_last = body["BorrowerLastName"].strip()
    borrower_name = f"{borrower_first} {borrower_last}"
    cardholder_name = f"{body['CardholderFirstName'].strip()} {body['CardholderLastName'].strip()}"
    # Optional link back to the cif-apply Firebase application that
    # triggered this card submission. Passed by apply.cashinflash.com
    # when the card step is filled in alongside an application. Stays
    # empty for standalone /if submissions that staff texted out.
    application_fb_id = (body.get("applicationFbId") or "").strip()[:128]
    billing_zip = body["BillingZip"].strip()
    submission_id = str(uuid.uuid4())
    submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    # Envelope-encrypt the full sensitive payload as one JSON blob.
    secret_blob = json.dumps({
        "card_number": pan,
        "cvv": cvv,
        "card_type": brand,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "cardholder_name": cardholder_name,
        "billing_zip": billing_zip,
    }, separators=(",", ":")).encode("utf-8")
    try:
        ciphertext_b64 = _encrypt(secret_blob, submission_id)
    except ClientError as e:
        log.exception("KMS encrypt failed: %s", e)
        return _json_response(502, {"error": "encryption_failed"})

    ttl_epoch = int(time.time()) + TTL_SECONDS
    ddb_item: Dict[str, Any] = {
        "submission_id":         {"S": submission_id},
        "ciphertext_b64":        {"S": ciphertext_b64},
        "borrower_name":         {"S": borrower_name},
        "borrower_first_name":   {"S": borrower_first},
        "borrower_last_name":    {"S": borrower_last},
        "cardholder_name":       {"S": cardholder_name},
        "last4":                 {"S": last4},
        "brand":                 {"S": brand},
        "exp_month":             {"N": str(exp_month)},
        "exp_year":              {"N": str(exp_year)},
        "billing_zip":           {"S": billing_zip},
        "submitted_at":          {"S": submitted_at},
        "status":                {"S": "pending"},
        "ttl_epoch":             {"N": str(ttl_epoch)},
    }
    if application_fb_id:
        ddb_item["application_fb_id"] = {"S": application_fb_id}
    try:
        _ddb.put_item(TableName=IF_DDB_TABLE, Item=ddb_item)
    except ClientError as e:
        log.exception("DDB put_item failed: %s", e)
        return _json_response(502, {"error": "storage_failed"})

    log.info("IF submission stored id=%s brand=%s last4=%s app_fb_id=%s",
             submission_id, brand, last4, application_fb_id or "-")

    _send_staff_notification(submission_id, {
        "borrower_name": borrower_name,
        "cardholder_name": cardholder_name,
        "brand": brand,
        "last4": last4,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "zip": billing_zip,
        "submitted_at": submitted_at,
    })

    # Do NOT echo card data. Just confirm to the browser.
    return _json_response(200, {
        "success": True,
        "submissionId": submission_id,
        "brand": brand,
        "last4": last4,
        "applicationFbId": application_fb_id or None,
    })


def _list_auth_ok(event: Dict[str, Any]) -> bool:
    """X-View-Secret check shared by list + view."""
    headers = event.get("headers") or {}
    got = headers.get("x-view-secret") or headers.get("X-View-Secret") or ""
    # Constant-time compare — a plain `==` leaks the secret one byte at a
    # time via response-timing. compare_digest is O(len) regardless of match.
    return bool(IF_VIEW_SHARED_SECRET) and hmac.compare_digest(got, IF_VIEW_SHARED_SECRET)


def list_submissions(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/if/list — return metadata for all non-expired submissions.

    No PAN, CVV, card_ref, or ciphertext in the response. Just enough
    for the staff dashboard to render a table and link to each view
    page.

    Auth: same X-View-Secret header as /view.
    """
    if not _list_auth_ok(event):
        log.warning("IF list unauthorized call")
        return _json_response(401, {"error": "unauthorized"})

    items: list = []
    try:
        # Volume is low (handful per day); full-table scan is fine.
        paginator = _ddb.get_paginator("scan")
        for page in paginator.paginate(
            TableName=IF_DDB_TABLE,
            ProjectionExpression=(
                "submission_id, borrower_name, cardholder_name, brand, "
                "last4, exp_month, exp_year, billing_zip, submitted_at, "
                "#s, ttl_epoch, application_fb_id"
            ),
            ExpressionAttributeNames={"#s": "status"},
        ):
            for it in page.get("Items", []):
                items.append({
                    "submissionId":    it.get("submission_id",   {}).get("S"),
                    "borrowerName":    it.get("borrower_name",   {}).get("S"),
                    "cardholderName":  it.get("cardholder_name", {}).get("S"),
                    "brand":           it.get("brand",           {}).get("S"),
                    "last4":           it.get("last4",           {}).get("S"),
                    "expMonth":        int(it.get("exp_month",   {}).get("N") or 0) or None,
                    "expYear":         int(it.get("exp_year",    {}).get("N") or 0) or None,
                    "billingZip":      it.get("billing_zip",     {}).get("S"),
                    "submittedAt":     it.get("submitted_at",    {}).get("S"),
                    "status":          it.get("status",          {}).get("S"),
                    "ttlEpoch":        int(it.get("ttl_epoch",   {}).get("N") or 0) or None,
                    "applicationFbId": it.get("application_fb_id", {}).get("S") or None,
                })
    except ClientError as e:
        log.exception("DDB scan failed: %s", e)
        return _json_response(502, {"error": "storage_failed"})

    # Newest first.
    items.sort(key=lambda x: x.get("submittedAt") or "", reverse=True)
    return _json_response(200, {"submissions": items, "count": len(items)})


def _load_and_decrypt(submission_id: str) -> Tuple[Optional[Dict[str, Any]],
                                                   Optional[Dict[str, Any]],
                                                   Optional[Dict[str, Any]]]:
    """Fetch + decrypt one submission. Returns (item, payload, error_response).

    On success: (item_dict, payload_dict, None).
    On miss/failure: (None, None, json_response_dict ready to return).
    """
    try:
        resp = _ddb.get_item(
            TableName=IF_DDB_TABLE,
            Key={"submission_id": {"S": submission_id}},
        )
    except ClientError as e:
        log.exception("DDB get_item failed: %s", e)
        return None, None, _json_response(502, {"error": "storage_failed"})

    item = resp.get("Item")
    if not item:
        return None, None, _json_response(404, {"error": "not_found"})

    ciphertext_b64 = item.get("ciphertext_b64", {}).get("S") or ""
    try:
        plaintext = _decrypt(ciphertext_b64, submission_id)
    except ClientError as e:
        log.exception("KMS decrypt failed: %s", e)
        return None, None, _json_response(502, {"error": "decryption_failed"})
    try:
        payload = json.loads(plaintext)
    except ValueError:
        return None, None, _json_response(502, {"error": "decode_failed"})
    return item, payload, None


def _mark_status(submission_id: str, new_status: str) -> None:
    """Best-effort status update; never raises."""
    try:
        _ddb.update_item(
            TableName=IF_DDB_TABLE,
            Key={"submission_id": {"S": submission_id}},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": {"S": new_status}},
        )
    except ClientError as e:
        log.warning("IF mark_status failed id=%s status=%s err=%s",
                    submission_id, new_status, e)


def _delete_record(submission_id: str) -> None:
    try:
        _ddb.delete_item(
            TableName=IF_DDB_TABLE,
            Key={"submission_id": {"S": submission_id}},
        )
    except ClientError as e:
        log.warning("IF delete failed id=%s err=%s", submission_id, e)


def view(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/if/view/{id} — shared-secret auth'd, reveal without delete.

    Staff dashboard calls this with `X-View-Secret: <secret>` header.
    Marks the record as 'viewed' so we know it was opened, but does
    NOT delete — so staff can come back and push to Vergent or mark
    it processed manually. The vault record self-deletes via TTL
    (72h) if no further action is taken.
    """
    if not _list_auth_ok(event):
        log.warning("IF view unauthorized call")
        return _json_response(401, {"error": "unauthorized"})

    path_params = event.get("pathParameters") or {}
    submission_id = path_params.get("id") or ""
    if not submission_id:
        return _json_response(400, {"error": "missing_id"})

    item, payload, err = _load_and_decrypt(submission_id)
    if err is not None:
        return err

    _mark_status(submission_id, "viewed")

    log.info("IF submission viewed id=%s brand=%s last4=%s",
             submission_id, payload.get("card_type"),
             (payload.get("card_number") or "")[-4:])

    # Card number is masked to last-4 and CVV is omitted entirely. The
    # staff dashboard never needs raw cardholder data on the wire —
    # push_to_vergent reads the full PAN+CVV from the encrypted vault
    # server-side. This way a leaked X-View-Secret can't yield a full
    # PAN/CVV dump; the blast radius is last-4 + expiry + name.
    _pan = payload.get("card_number") or ""
    return _json_response(200, {
        "submissionId": submission_id,
        "borrowerName":   item.get("borrower_name",   {}).get("S"),
        "cardholderName": item.get("cardholder_name", {}).get("S"),
        "cardLast4":      _pan[-4:] if _pan else "",
        "cardType":       payload.get("card_type"),
        "expMonth":       payload.get("exp_month"),
        "expYear":        payload.get("exp_year"),
        "billingZip":     payload.get("billing_zip"),
        "submittedAt":    item.get("submitted_at",    {}).get("S"),
        "applicationFbId": item.get("application_fb_id", {}).get("S") or None,
        "status":         "viewed",
    })


def _vergent_match_by_name(first: str, last: str) -> Tuple[list, str]:
    """Search Vergent for a consumer customer matching first+last.

    Returns (matches, error_tag). matches is a list of dicts each
    with at least {customerId, firstName, lastName}. error_tag is
    "" on success or a short reason string for logging.

    Vergent's APIM search is fuzzy by default — we do a strict
    case-insensitive equality filter on first+last server-side so
    we don't accidentally push to a Smith when the borrower is
    Smithfield.
    """
    f = (first or "").strip()
    l = (last or "").strip()
    if not (f and l):
        return [], "missing_name"
    try:
        # user_type=1 == consumer (verified earlier in search.py).
        results = vergent.customer_search(
            first_name=f, last_name=l, user_type=1,
        )
    except Exception as e:
        log.warning("Vergent customer_search failed for %s %s: %s", f, l, e)
        return [], "search_failed"
    if not isinstance(results, list):
        return [], "no_results"
    fl = f.lower()
    ll = l.lower()
    filtered = [
        r for r in results
        if isinstance(r, dict)
        and (r.get("firstName") or "").strip().lower() == fl
        and (r.get("lastName") or "").strip().lower() == ll
    ]
    return filtered, ""


def push_to_vergent(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/if/push-to-vergent
       body: {submissionId, vergentCustomerId?}

    Three steps:
      0. If no vergentCustomerId in the body, look up the customer
         in Vergent by the borrower's first+last name. If exactly
         one match is found we use it automatically. If zero or
         many, we return a structured response so the dashboard
         can prompt the staff member to disambiguate.
      1. Tokenize the card via Repay CardSafe StoreCard.
      2. Save the tokenized card on the Vergent customer record
         via /V1/PostCustomerCardTokenized with card_ref=<repay
         token>.

    On success: mark processed, delete vault entry, return
    {success: true, vergentCardId, vergentCustomerId}.
    On any failure: leave the vault record intact so staff can retry.
    """
    if not _list_auth_ok(event):
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    submission_id = (body.get("submissionId") or "").strip()
    vergent_cid = (body.get("vergentCustomerId") or "").strip()
    if not submission_id:
        return _json_response(400, {"error": "missing_submission_id"})
    if vergent_cid and not (vergent_cid.isdigit() and 1 <= len(vergent_cid) <= 10):
        return _json_response(400, {"error": "invalid_customer_id"})

    item, payload, err = _load_and_decrypt(submission_id)
    if err is not None:
        return err

    # ── Auto-match by borrower name when staff didn't specify an ID ──
    auto_matched = False
    if not vergent_cid:
        first = item.get("borrower_first_name", {}).get("S") or ""
        last = item.get("borrower_last_name", {}).get("S") or ""
        if not (first and last):
            # Older submission without split names — split borrower_name.
            full = item.get("borrower_name", {}).get("S") or ""
            parts = full.split(" ", 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
        matches, search_err = _vergent_match_by_name(first, last)
        if search_err == "search_failed":
            return _json_response(502, {"error": "vergent_search_failed",
                                        "detail": "Couldn't reach Vergent to look up the customer."})
        if not matches:
            log.info("IF push: no Vergent match for %s %s id=%s", first, last, submission_id)
            return _json_response(404, {
                "error": "no_vergent_match",
                "borrowerName": f"{first} {last}".strip(),
                "detail": "Couldn't find a Vergent customer with that name. Enter the customer ID manually.",
            })
        if len(matches) > 1:
            log.info("IF push: ambiguous Vergent match for %s %s id=%s count=%d",
                     first, last, submission_id, len(matches))
            return _json_response(200, {
                "success": False,
                "error": "ambiguous_match",
                "borrowerName": f"{first} {last}".strip(),
                "candidates": [{
                    "customerId": str(m.get("customerId") or ""),
                    "firstName": m.get("firstName") or "",
                    "lastName": m.get("lastName") or "",
                    "phones": (m.get("mobileNumbers") or [])[:2],
                } for m in matches[:10]],
            })
        vergent_cid = str(matches[0].get("customerId") or "")
        auto_matched = True
        log.info("IF push: auto-matched %s %s -> Vergent cid=%s id=%s",
                 first, last, vergent_cid, submission_id)
        if not vergent_cid:
            return _json_response(502, {"error": "vergent_match_no_id"})

    pan = payload.get("card_number") or ""
    cvv = payload.get("cvv") or ""
    name = payload.get("cardholder_name") or item.get("cardholder_name", {}).get("S") or ""
    zip_code = payload.get("billing_zip") or ""
    last4 = pan[-4:] if pan else ""
    try:
        exp_month = int(payload.get("exp_month") or 0)
        exp_year = int(payload.get("exp_year") or 0)
    except (TypeError, ValueError):
        return _json_response(400, {"error": "exp_invalid"})

    log.info("IF push starting id=%s cid=%s last4=%s",
             submission_id, vergent_cid, last4)

    # Step 1 — Repay CardSafe.
    token, info = _cardsafe_store(
        pan=pan, exp_month=exp_month, exp_year=exp_year,
        cvv=cvv, name_on_card=name, zip_code=zip_code,
        customer_key=vergent_cid,
    )
    if not token:
        log.warning("IF push: CardSafe failed id=%s info=%s", submission_id, info)
        return _json_response(502, {"error": "tokenization_failed", "detail": info})

    log.info("IF push: CardSafe ok id=%s last4=%s token_len=%d",
             submission_id, last4, len(token))

    # Step 2 — Vergent /V1/PostCustomerCardTokenized.
    # Schema (snake_case, observed): id, company_id, customer_id,
    # card_type_id, card_holder, card_number, last_four_digits,
    # card_id, card_ref, expire_month, expire_year, ccv,
    # billing_zip_code.
    card_type = payload.get("card_type") or ""
    card_type_id = {
        "Visa": 2, "MasterCard": 1, "MASTERCARD": 1,
        "Amex": 3, "AMEX": 3, "Discover": 4,
    }.get(card_type, 0)
    v1_body = {
        "id": 0,
        "company_id": VERGENT_COMPANY_ID,
        "customer_id": int(vergent_cid),
        "card_type_id": card_type_id,
        "card_holder": name,
        "card_number": pan,
        "last_four_digits": last4,
        "card_id": "",
        "card_ref": token,
        "is_eligible_for_disbursement": False,
        "expire_month": exp_month,
        "expire_year": exp_year,
        "ccv": cvv,
        "billing_zip_code": zip_code,
    }
    status, resp, raw = _v1_request("POST", "/V1/PostCustomerCardTokenized", body=v1_body)

    if status not in (200, 201):
        flat_raw = (raw or "").replace("\n", " ").replace("\r", " ")
        log.warning("IF push: Vergent PostCustomerCardTokenized status=%s raw=%s",
                    status, flat_raw[:1500])
        return _json_response(502, {
            "error": "vergent_save_failed",
            "vergentStatus": status,
            "detail": flat_raw[:300],
        })

    if isinstance(resp, dict) and resp.get("Errors"):
        log.warning("IF push: Vergent returned errors id=%s errors=%s",
                    submission_id, resp.get("Errors"))
        return _json_response(200, {
            "success": False,
            "error": "card_declined",
            "errors": resp.get("Errors"),
        })

    new_card_id = resp.get("id") if isinstance(resp, dict) else None
    log.info("IF push success id=%s vergent_card_id=%s last4=%s",
             submission_id, new_card_id, last4)

    # Mark processed — do NOT auto-delete. Staff decides when to
    # purge the vault entry via POST /api/if/delete. The 30-day TTL
    # is the only safety net.
    _mark_status(submission_id, "processed")

    return _json_response(200, {
        "success": True,
        "submissionId": submission_id,
        "vergentCardId": new_card_id,
        "vergentCustomerId": int(vergent_cid),
        "last4": last4,
        "autoMatched": auto_matched,
    })


def mark_processed(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/if/mark-processed body: {submissionId}

    For when staff entered the card into Vergent manually and wants
    to drop the vault record without an automated push.
    """
    if not _list_auth_ok(event):
        return _json_response(401, {"error": "unauthorized"})
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    submission_id = (body.get("submissionId") or "").strip()
    if not submission_id:
        return _json_response(400, {"error": "missing_submission_id"})

    _mark_status(submission_id, "processed")
    log.info("IF submission marked processed (manual) id=%s", submission_id)
    return _json_response(200, {"success": True, "submissionId": submission_id})


def delete_submission(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/if/delete  body: {submissionId}

    Manual purge. Staff hits this from the dashboard when they're
    done with a submission (or want to clear one they created by
    mistake). No other endpoint deletes anymore — everything else
    just updates `status` and lets the record stay visible.
    """
    if not _list_auth_ok(event):
        return _json_response(401, {"error": "unauthorized"})
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})
    submission_id = (body.get("submissionId") or "").strip()
    if not submission_id:
        return _json_response(400, {"error": "missing_submission_id"})
    _delete_record(submission_id)
    log.info("IF submission deleted (manual) id=%s", submission_id)
    return _json_response(200, {"success": True, "submissionId": submission_id})


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    try:
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        if method == "OPTIONS":
            return _cors_preflight()

        path = http.get("path") or event.get("rawPath") or ""

        if method == "POST" and path.endswith("/api/if/submit"):
            return submit(event)
        if method == "GET" and path.endswith("/api/if/list"):
            return list_submissions(event)
        if method == "GET" and "/api/if/view/" in path:
            return view(event)
        if method == "POST" and path.endswith("/api/if/push-to-vergent"):
            return push_to_vergent(event)
        if method == "POST" and path.endswith("/api/if/mark-processed"):
            return mark_processed(event)
        if method == "POST" and path.endswith("/api/if/delete"):
            return delete_submission(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("IF handler unhandled: %s", exc)
        return _json_response(500, {"error": "internal_error"})
