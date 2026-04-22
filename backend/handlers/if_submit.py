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
  IF_VIEW_URL_BASE    e.g. https://app.cashinflash.com/if/view
  MFA_EMAIL_SENDER    verified SES From address (reuses auth-mfa var)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


# ─────────────────────────────────────────
# Globals / clients
# ─────────────────────────────────────────
log = logging.getLogger()
log.setLevel(logging.INFO)

_kms = boto3.client("kms")
_ddb = boto3.client("dynamodb")
_ses = boto3.client("ses")

IF_KMS_KEY_ID = os.environ.get("IF_KMS_KEY_ID", "alias/cif-portal-if-vault")
IF_DDB_TABLE = os.environ.get("IF_DDB_TABLE", "cif-portal-if-submissions-dev")
IF_NOTIFY_EMAIL = os.environ.get("IF_NOTIFY_EMAIL", "loans@cashinflash.com")
IF_VIEW_SHARED_SECRET = os.environ.get("IF_VIEW_SHARED_SECRET", "")
IF_VIEW_URL_BASE = os.environ.get("IF_VIEW_URL_BASE", "https://app.cashinflash.com/if/view")
EMAIL_SENDER = os.environ.get("MFA_EMAIL_SENDER", "no-reply@cashinflash.com")

# 72 hours — plenty of time for staff to process, then the record
# self-deletes via DynamoDB TTL. Shorter than PCI's 12-month
# retention cap for SAD (sensitive authentication data).
TTL_SECONDS = 72 * 60 * 60

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-View-Secret",
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
    for k in ("BorrowerFirstName", "BorrowerLastName",
              "CardholderFirstName", "CardholderLastName"):
        v = (body.get(k) or "").strip()
        if not v or len(v) > 60:
            return False, f"invalid_{k}"
    pan = _digits(body.get("CardNumber"))
    if not _luhn_ok(pan):
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
    if yy < 2024 or yy > 2099:
        return False, "exp_invalid"
    try:
        last_day_of_exp = datetime(yy if mm < 12 else yy + 1,
                                   mm + 1 if mm < 12 else 1, 1,
                                   tzinfo=timezone.utc)
    except ValueError:
        return False, "exp_invalid"
    if last_day_of_exp <= datetime.now(timezone.utc):
        return False, "exp_invalid"
    if not _ZIP_RE.match((body.get("BillingZip") or "").strip()):
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
# Notification email
# ─────────────────────────────────────────
def _send_staff_notification(submission_id: str,
                             meta: Dict[str, Any]) -> None:
    view_url = f"{IF_VIEW_URL_BASE}/{submission_id}"
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

    borrower_name = f"{body['BorrowerFirstName'].strip()} {body['BorrowerLastName'].strip()}"
    cardholder_name = f"{body['CardholderFirstName'].strip()} {body['CardholderLastName'].strip()}"
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
    try:
        _ddb.put_item(
            TableName=IF_DDB_TABLE,
            Item={
                "submission_id": {"S": submission_id},
                "ciphertext_b64": {"S": ciphertext_b64},
                "borrower_name":  {"S": borrower_name},
                "cardholder_name":{"S": cardholder_name},
                "last4":          {"S": last4},
                "brand":          {"S": brand},
                "exp_month":      {"N": str(exp_month)},
                "exp_year":       {"N": str(exp_year)},
                "billing_zip":    {"S": billing_zip},
                "submitted_at":   {"S": submitted_at},
                "status":         {"S": "pending"},
                "ttl_epoch":      {"N": str(ttl_epoch)},
            },
        )
    except ClientError as e:
        log.exception("DDB put_item failed: %s", e)
        return _json_response(502, {"error": "storage_failed"})

    log.info("IF submission stored id=%s brand=%s last4=%s",
             submission_id, brand, last4)

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
    })


def view(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/if/view/{id} — shared-secret auth'd, read-once.

    Staff dashboard calls this with `X-View-Secret: <secret>` header.
    On success we return plaintext card details AND delete the
    DynamoDB record so the same link can't be reused.
    """
    headers = event.get("headers") or {}
    # HTTP API lowercases header names
    got_secret = (headers.get("x-view-secret")
                  or headers.get("X-View-Secret") or "")
    if not IF_VIEW_SHARED_SECRET or got_secret != IF_VIEW_SHARED_SECRET:
        log.warning("IF view unauthorized call")
        return _json_response(401, {"error": "unauthorized"})

    path_params = event.get("pathParameters") or {}
    submission_id = path_params.get("id") or ""
    if not submission_id:
        return _json_response(400, {"error": "missing_id"})

    try:
        resp = _ddb.get_item(
            TableName=IF_DDB_TABLE,
            Key={"submission_id": {"S": submission_id}},
        )
    except ClientError as e:
        log.exception("DDB get_item failed: %s", e)
        return _json_response(502, {"error": "storage_failed"})

    item = resp.get("Item")
    if not item:
        return _json_response(404, {"error": "not_found"})

    ciphertext_b64 = item.get("ciphertext_b64", {}).get("S") or ""
    try:
        plaintext = _decrypt(ciphertext_b64, submission_id)
    except ClientError as e:
        log.exception("KMS decrypt failed: %s", e)
        return _json_response(502, {"error": "decryption_failed"})

    try:
        payload = json.loads(plaintext)
    except ValueError:
        return _json_response(502, {"error": "decode_failed"})

    # Purge the record so this link can't be re-used. If the delete
    # fails we still return the plaintext (better to serve the card
    # once and log a cleanup failure than to 500 after decrypting).
    try:
        _ddb.delete_item(
            TableName=IF_DDB_TABLE,
            Key={"submission_id": {"S": submission_id}},
        )
    except ClientError as e:
        log.error("IF view: delete-after-read failed id=%s err=%s",
                  submission_id, e)

    log.info("IF submission served id=%s brand=%s last4=%s (record deleted)",
             submission_id, payload.get("card_type"), (payload.get("card_number") or "")[-4:])

    return _json_response(200, {
        "submissionId": submission_id,
        "borrowerName":   item.get("borrower_name",   {}).get("S"),
        "cardholderName": item.get("cardholder_name", {}).get("S"),
        "cardNumber":     payload.get("card_number"),
        "cardType":       payload.get("card_type"),
        "expMonth":       payload.get("exp_month"),
        "expYear":        payload.get("exp_year"),
        "cvv":            payload.get("cvv"),
        "billingZip":     payload.get("billing_zip"),
        "submittedAt":    item.get("submitted_at",    {}).get("S"),
    })


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
        if method == "GET" and "/api/if/view/" in path:
            return view(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("IF handler unhandled: %s", exc)
        return _json_response(500, {"error": "internal_error"})
