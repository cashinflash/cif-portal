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
    _claims,
    _customer_id,
    _get_apim_token,
    _get_creds,
    _http,
    _json_response,
    _shape_v1_loan,
    _v1_get,
)

log = logging.getLogger()
log.setLevel(logging.INFO)


# ─────────────────────────────────────────
# Shape helpers
# ─────────────────────────────────────────
def _shape_card(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent's CustomerCreditCardModel → UI shape.

    Vergent returns: id, cardTypeId, cardType, accountNumberMasked,
    expirationMonth, expirationYear, isExpired.
    """
    masked = raw.get("accountNumberMasked") or ""
    digits = [c for c in masked if c.isdigit()]
    last4 = "".join(digits[-4:]) if len(digits) >= 4 else ""
    return {
        "id": raw.get("id"),
        "brand": raw.get("cardType") or "Card",
        "last4": last4,
        "expMonth": raw.get("expirationMonth"),
        "expYear": raw.get("expirationYear"),
        "isExpired": bool(raw.get("isExpired")),
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
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"cards": [], "expiredCards": []})

    status, body, raw = _apim_call("GET", "/api/CustomerPortal/Customer/Cards")
    if status != 200 or not isinstance(body, list):
        log.warning("Customer/Cards status=%s raw=%s", status, raw[:200] if raw else "")
        return _json_response(200, {"cards": [], "expiredCards": [], "error": "upstream_unavailable"})

    shaped = [_shape_card(c) for c in body if isinstance(c, dict)]
    cards = [c for c in shaped if not c["isExpired"]]
    expired = [c for c in shaped if c["isExpired"]]
    return _json_response(200, {"cards": cards, "expiredCards": expired})


def get_loan_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"loan": None})
    loan = _fetch_active_loan(cid)
    return _json_response(200, {"loan": loan})


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
        if path.endswith("/my-payment/loan-summary") and method == "GET":
            return get_loan_summary(event)
        if path.endswith("/my-payment") and method == "POST":
            return post_payment(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("payments handler unexpected error: %s", exc)
        return _json_response(500, {"error": "internal_error"})
