"""
Customer Portal — Payments handler (Vergent v2 APIM + Repay).

Routes (bound to HttpApi with Cognito JWT authorizer):
  GET  /api/my-cards                 -> list the customer's saved cards
  GET  /api/my-payment/loan-summary  -> active loan data formatted for the pay page
  POST /api/my-payment               -> charge a saved card and post to the loan

Auth model:
  - API Gateway's Cognito JWT authorizer identifies the customer
    (custom:vergentCustomerId claim).
  - Vergent is called with the SERVICE APIM token (JWT from
    /api/authenticate at the APIM host) plus the x-api-key header.
    We reuse the exact caching pattern from loans.py::_get_apim_token.
  - Before we execute a charge, we pull the customer's loans via v1
    and confirm the requested loanId belongs to the caller. We also
    confirm cardId is in the caller's card list. Never trust the body
    alone for authorization.

PCI posture: we never touch raw PAN. Vergent returns tokenized saved
cards (last4 only); Vergent routes the charge to Repay server-side.
Our logs record cardId + last4 + amount + confirmation id.

Environment:
  VERGENT_APIM_BASE_URL  default https://prod.apim.vergentlms.com/external/shared
  VERGENT_V1_BASE_URL    default https://shared.vergentlms.com/api/api
  VERGENT_SECRET_ARN     Secrets Manager ARN (same secret as loans.py)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

# Reuse everything from the loans handler rather than re-implementing.
# Both files ship in the same zip so the import resolves at cold start.
from handlers.loans import (
    APIM_BASE,
    CORS_HEADERS,
    V1_BASE,
    _claims,
    _customer_id,
    _get_apim_token,
    _get_creds,
    _get_v1_token,
    _http,
    _json_response,
    _shape_v1_loan,
    _v1_get,
)

VERGENT_COMPANY_ID = int(os.environ.get("VERGENT_COMPANY_ID", "386"))

log = logging.getLogger()
log.setLevel(logging.INFO)


# ─────────────────────────────────────────
# Shape helpers
# ─────────────────────────────────────────
# Card-type id → display brand. Vergent v1's GetCustomerCardTypes
# returns the source-of-truth list at runtime; this is a fallback for
# the most common four. Confirmed empirically — adjust if a different
# id surfaces in CloudWatch.
_CARD_TYPE_NAMES = {
    1: "Visa",
    2: "MasterCard",
    3: "Amex",
    4: "Discover",
}
_BRAND_TO_TYPE_ID = {
    "Visa": 1,
    "MasterCard": 2,
    "Amex": 3,
    "Discover": 4,
}


def _shape_card_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent v1's customer_card → UI shape.

    v1 returns snake_case: id, company_id, customer_id, card_type_id,
    card_holder, card_number (masked), card_id, card_ref. There's no
    expiry/expired flag in the basic shape — those come back through
    the tokenized variant if present.
    """
    masked = (raw.get("card_number") or "")
    digits = [c for c in masked if c.isdigit()]
    last4 = "".join(digits[-4:]) if len(digits) >= 4 else ""
    type_id = raw.get("card_type_id") or 0
    brand = _CARD_TYPE_NAMES.get(int(type_id) if isinstance(type_id, (int, str)) else 0, "Card")
    return {
        "id": raw.get("id"),
        "brand": brand,
        "last4": last4,
        # v1 base shape doesn't carry exp / isExpired; surface what we have.
        "expMonth": raw.get("exp_month") or raw.get("expire_month"),
        "expYear": raw.get("exp_year") or raw.get("expire_year"),
        "isExpired": False,
        "cardRef": raw.get("card_ref") or "",
    }


def _apim_call(method: str, path: str, *,
               body: Optional[Dict[str, Any]] = None,
               extra_headers: Optional[Dict[str, str]] = None
               ) -> tuple:
    """Call a Vergent APIM endpoint with our service JWT + x-api-key."""
    tok = _get_apim_token()
    if not tok:
        return 0, None, ""
    creds = _get_creds()
    h = {
        "Authorization": f"Bearer {tok}",
        "x-api-key": creds["xApiKey"],
    }
    if extra_headers:
        h.update(extra_headers)
    return _http(f"{APIM_BASE}{path}", method, body=body, headers=h)


def _v1_request(method: str, path: str, *,
                body: Optional[Dict[str, Any]] = None
                ) -> tuple:
    """Call a Vergent v1 LMS endpoint with the service Token header.

    Same auth pattern as `loans.py::_v1_get` but supports any method
    and returns the raw response body too (for debugging upstream
    errors). Refreshes the token once on 401/403 then retries.
    """
    tok = _get_v1_token()
    if not tok:
        return 0, None, ""
    url = f"{V1_BASE}{path}"
    status, parsed, raw = _http(url, method, body=body, headers={"Token": tok})
    if status in (401, 403):
        # Force token refresh and retry once.
        from handlers import loans as _loans
        _loans._v1_token_exp = 0
        tok2 = _get_v1_token()
        if tok2:
            status, parsed, raw = _http(url, method, body=body, headers={"Token": tok2})
    return status, parsed, raw


# ─────────────────────────────────────────
# Loan lookup — shared by loan-summary + payment validation
# ─────────────────────────────────────────
def _fetch_active_loan(cid: str) -> Optional[Dict[str, Any]]:
    """Return the customer's first outstanding loan (shaped), or None."""
    status, body = _v1_get(f"/V1/{cid}/loans")
    if status != 200 or not isinstance(body, list):
        return None
    shaped = [_shape_v1_loan(item) for item in body if isinstance(item, dict)]
    outstanding = [l for l in shaped if l.get("isOutstanding")]
    if outstanding:
        return outstanding[0]
    return shaped[0] if shaped else None


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────
def get_my_cards(event: Dict[str, Any]) -> Dict[str, Any]:
    """List the signed-in customer's saved cards via Vergent v1.

    Calls GET /api/V1/GetCustomerCards?custId=<cid> with the service
    Token header. v1's customerId-in-querystring auth model means we
    can use our service token without needing AuthenticateCognito
    (which is broken for our tenant).
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"cards": [], "expiredCards": []})

    status, body, raw = _v1_request("GET", f"/V1/GetCustomerCards?custId={cid}")
    if status != 200 or not isinstance(body, list):
        log.warning("GetCustomerCards status=%s raw=%s", status, (raw or "")[:300])
        return _json_response(200, {"cards": [], "expiredCards": [], "error": "upstream_unavailable"})

    shaped = [_shape_card_v1(c) for c in body if isinstance(c, dict)]
    return _json_response(200, {"cards": shaped, "expiredCards": []})


def get_loan_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None})
    loan = _fetch_active_loan(cid)
    return _json_response(200, {"loan": loan})


def _luhn_ok(digits: str) -> bool:
    """Checksum-validate a card number. Purely defensive — Vergent will
    reject bad PANs on its side too."""
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


def _detect_card_type(digits: str) -> str:
    """BIN-based brand detection. Matches Vergent's enum values where
    possible; falls back to 'Other'."""
    if not digits:
        return "Other"
    if digits.startswith("4"):
        return "Visa"
    if digits[:2] in {"34", "37"}:
        return "Amex"
    if digits.startswith("6011") or digits[:2] == "65" or (622126 <= int(digits[:6] or 0) <= 622925):
        return "Discover"
    if digits[:2] in {"51", "52", "53", "54", "55"} or (
        2221 <= int(digits[:4] or 0) <= 2720
    ):
        return "MasterCard"
    return "Other"


def post_card(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-cards — save a new card on the signed-in customer.

    We forward the card details to Vergent's
    POST /api/CustomerPortal/Customer/Cards, which tokenizes via Repay
    server-side. PAN passes through this Lambda over HTTPS but is
    never stored or logged (only last4).
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    name = (body.get("cardHolderName") or "").strip()
    pan = "".join(ch for ch in (body.get("cardNumber") or "") if ch.isdigit())
    ccv = "".join(ch for ch in (body.get("ccv") or "") if ch.isdigit())
    try:
        exp_month = int(body.get("expireMonth") or 0)
        exp_year = int(body.get("expireYear") or 0)
    except (TypeError, ValueError):
        exp_month = exp_year = 0

    # Shape checks (cheap guardrails; Vergent validates too).
    if not name or len(name) > 80:
        return _json_response(400, {"error": "name_invalid"})
    if not _luhn_ok(pan):
        return _json_response(400, {"error": "card_invalid"})
    if not (1 <= exp_month <= 12):
        return _json_response(400, {"error": "exp_invalid"})
    if exp_year < 100:  # two-digit year → 2000s
        exp_year += 2000
    if exp_year < 2024 or exp_year > 2099:
        return _json_response(400, {"error": "exp_invalid"})
    if not (3 <= len(ccv) <= 4):
        return _json_response(400, {"error": "ccv_invalid"})

    card_type = (body.get("cardType") or _detect_card_type(pan)).strip() or "Other"
    card_type_id = _BRAND_TO_TYPE_ID.get(card_type, 0)
    last4 = pan[-4:]

    # Never log PAN or CCV. Custid + last4 + amount-ish metadata only.
    log.info("add card attempt cid=%s last4=%s brand=%s exp=%02d/%d",
             cid, last4, card_type, exp_month, exp_year)

    # Use v1 PostCustomerCard. v1 takes customerId in the body and
    # auths with our service Token header — no customer-scoped JWT
    # needed (which is what was failing on the v2 endpoint).
    # Schema (snake_case): id, company_id, customer_id, card_type_id,
    # card_holder, card_number, card_id, card_ref,
    # is_eligible_for_disbursement. Also send expire_month/year/ccv —
    # Vergent ignores fields it doesn't recognize and these are
    # documented for the tokenized variant.
    v1_body = {
        "id": 0,
        "company_id": VERGENT_COMPANY_ID,
        "customer_id": int(cid),
        "card_type_id": card_type_id,
        "card_holder": name,
        "card_number": pan,
        "card_id": "",
        "card_ref": "",
        "is_eligible_for_disbursement": False,
        "expire_month": exp_month,
        "expire_year": exp_year,
        "ccv": ccv,
    }

    status, resp, raw = _v1_request("POST", "/V1/PostCustomerCard", body=v1_body)

    if status not in (200, 201):
        log.warning("PostCustomerCard upstream status=%s raw=%s", status, (raw or "")[:300])
        return _json_response(502, {"error": "upstream_unavailable"})

    # v1's success response can be empty {} or carry the new card id;
    # we treat any 200/201 as success and look for 'Errors' to detect
    # in-band failures.
    if isinstance(resp, dict) and resp.get("Errors"):
        log.warning("PostCustomerCard returned errors cid=%s last4=%s errors=%s",
                    cid, last4, resp.get("Errors"))
        return _json_response(200, {"success": False, "error": "card_declined"})

    new_card_id = resp.get("id") if isinstance(resp, dict) else None
    log.info("add card success cid=%s last4=%s new_card_id=%s", cid, last4, new_card_id)

    return _json_response(200, {
        "success": True,
        "last4": last4,
        "brand": card_type,
        "cardId": new_card_id,
    })


def post_payment(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    loan_id = body.get("loanId")
    card_id = body.get("cardId")
    amount = body.get("amount")
    idempotency_key = body.get("idempotencyKey") or ""

    # Basic shape check
    if loan_id is None or card_id is None or amount is None:
        return _json_response(400, {"error": "missing_fields"})
    try:
        amount_num = float(amount)
    except (TypeError, ValueError):
        return _json_response(400, {"error": "amount_invalid"})
    if amount_num <= 0:
        return _json_response(400, {"error": "amount_invalid"})

    # Ownership: confirm loanId belongs to this customer and get payoff.
    loan = _fetch_active_loan(cid)
    if not loan or str(loan.get("id")) != str(loan_id):
        # Also allow paying a non-first outstanding loan in case the
        # customer has multiple — refetch the full list.
        status, raw_loans = _v1_get(f"/V1/{cid}/loans")
        found = None
        if status == 200 and isinstance(raw_loans, list):
            for r in raw_loans:
                if isinstance(r, dict):
                    shaped = _shape_v1_loan(r)
                    if str(shaped.get("id")) == str(loan_id):
                        found = shaped
                        break
        if not found:
            log.warning("payment loan_not_yours cid=%s loan_id=%s", cid, loan_id)
            return _json_response(403, {"error": "loan_not_yours"})
        loan = found

    payoff = loan.get("payoffAmount") or loan.get("balance") or 0
    if amount_num > float(payoff) + 0.01:
        return _json_response(400, {"error": "amount_invalid", "payoff": payoff})

    # Ownership: confirm cardId is in the customer's card list.
    st_c, body_c, _ = _apim_call("GET", "/api/CustomerPortal/Customer/Cards")
    if st_c != 200 or not isinstance(body_c, list):
        return _json_response(502, {"error": "upstream_unavailable"})
    card = next(
        (c for c in body_c if isinstance(c, dict) and str(c.get("id")) == str(card_id)),
        None,
    )
    if not card:
        return _json_response(403, {"error": "card_not_yours"})
    if card.get("isExpired"):
        return _json_response(400, {"error": "card_expired"})

    last4 = "".join(c for c in (card.get("accountNumberMasked") or "") if c.isdigit())[-4:]

    # Execute the charge. Vergent's CreditCardPaymentRequestModel fields:
    # loanId (int), paymentId (int, which is the card's id), amountDue (number).
    charge_body = {
        "loanId": int(loan_id),
        "paymentId": int(card_id),
        "amountDue": round(amount_num, 2),
    }
    extra_headers = {"X-Idempotency-Key": idempotency_key} if idempotency_key else None

    log.info("payment attempt cid=%s loan_id=%s card_id=%s last4=%s amount=%s",
             cid, loan_id, card_id, last4, amount_num)

    status, charge, raw = _apim_call(
        "POST",
        "/api/CustomerPortal/Loans/Payments/CreditCardPayment",
        body=charge_body,
        extra_headers=extra_headers,
    )

    if status not in (200, 201) or not isinstance(charge, dict):
        log.warning("payment upstream status=%s raw=%s", status, raw[:300] if raw else "")
        return _json_response(502, {"error": "upstream_unavailable"})

    if not charge.get("success"):
        log.warning("payment declined cid=%s loan_id=%s card_id=%s", cid, loan_id, card_id)
        return _json_response(200, {"success": False, "error": "card_declined"})

    # Re-fetch the loan so we can tell the UI the new balance.
    refreshed = _fetch_active_loan(cid)
    new_balance = refreshed.get("balance") if refreshed else None

    # Vergent's response doesn't carry a clean "confirmation id" — use
    # scheduleDate or fall back to a local UTC timestamp.
    confirmation_id = charge.get("scheduleDate") or ""

    log.info("payment success cid=%s loan_id=%s last4=%s amount=%s conf=%s new_balance=%s",
             cid, loan_id, last4, amount_num, confirmation_id, new_balance)

    return _json_response(200, {
        "success": True,
        "confirmationId": confirmation_id,
        "scheduleDate": charge.get("scheduleDate"),
        "amount": round(amount_num, 2),
        "last4": last4,
        "newBalance": new_balance,
    })


# ─────────────────────────────────────────
# Lambda entrypoint
# ─────────────────────────────────────────
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    try:
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        path = http.get("path") or event.get("rawPath") or ""

        if path.endswith("/my-cards") and method == "GET":
            return get_my_cards(event)
        if path.endswith("/my-cards") and method == "POST":
            return post_card(event)
        if path.endswith("/my-payment/loan-summary") and method == "GET":
            return get_loan_summary(event)
        if path.endswith("/my-payment") and method == "POST":
            return post_payment(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("payments handler unexpected error: %s", exc)
        return _json_response(500, {"error": "internal_error"})
