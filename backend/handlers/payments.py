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
# Static-fallback brand→id guesses. Only used if GetCustomerCardTypes
# fails; Vergent is the source of truth and we cache their mapping
# module-globally at first use.
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

# Per-container cache. Reset on cold start. {lower_brand_name: int_id}
_card_types_by_name: Optional[Dict[str, int]] = None
_card_types_by_id: Optional[Dict[int, str]] = None


def _brand_key(s: str) -> str:
    """Normalize a brand string for matching across Vergent's inconsistencies."""
    s = (s or "").strip().lower()
    # Collapse any whitespace and common variants.
    s = s.replace("master card", "mastercard")
    s = s.replace("american express", "amex")
    s = s.replace(" ", "")
    return s


def _load_card_types() -> None:
    """Populate _card_types_by_name from Vergent once per warm container.

    Vergent returns a FLAT dict {"Visa": 2, "MasterCard": 1, ...} —
    not the list-of-objects Swagger suggests. Handle both shapes.
    """
    global _card_types_by_name, _card_types_by_id
    if _card_types_by_name is not None:
        return
    status, body, _raw = _v1_request("GET", "/V1/GetCustomerCardTypes")
    names: Dict[str, int] = {}
    ids: Dict[int, str] = {}
    if status == 200 and isinstance(body, dict):
        # Flat-dict format {name: id} — observed on our tenant.
        flat_ok = True
        for k, v in body.items():
            try:
                names[_brand_key(str(k))] = int(v)
                ids[int(v)] = str(k)
            except (TypeError, ValueError):
                flat_ok = False
                break
        if not flat_ok:
            names.clear(); ids.clear()
            # Try nested variants: {CardTypes: [...]}, {items: [...]}
            items = body.get("CardTypes") or body.get("items") or body.get("Items")
            if isinstance(items, list):
                for t in items:
                    if isinstance(t, dict):
                        name = (t.get("name") or t.get("Name") or t.get("TypeName") or "").strip()
                        tid = t.get("id") or t.get("Id") or t.get("TypeId")
                        if name and tid is not None:
                            try:
                                tid_int = int(tid)
                            except (TypeError, ValueError):
                                continue
                            names[_brand_key(name)] = tid_int
                            ids[tid_int] = name
    elif status == 200 and isinstance(body, list):
        for t in body:
            if isinstance(t, dict):
                name = (t.get("name") or t.get("Name") or t.get("TypeName") or "").strip()
                tid = t.get("id") or t.get("Id") or t.get("TypeId")
                if name and tid is not None:
                    try:
                        tid_int = int(tid)
                    except (TypeError, ValueError):
                        continue
                    names[_brand_key(name)] = tid_int
                    ids[tid_int] = name

    if not names:
        log.warning("GetCustomerCardTypes yielded no usable mapping; falling back to static guesses. body=%s",
                    str(body)[:300] if body else None)
        names = {_brand_key(k): v for k, v in _BRAND_TO_TYPE_ID.items()}
        ids = {v: k for k, v in _BRAND_TO_TYPE_ID.items()}
    else:
        log.info("GetCustomerCardTypes loaded: %s", ids)
    _card_types_by_name = names
    _card_types_by_id = ids


def _vergent_card_type_id(brand: str) -> int:
    """Translate our detected brand name → Vergent's numeric card_type_id."""
    _load_card_types()
    return (_card_types_by_name or {}).get(_brand_key(brand), 0)


def _shape_card_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent v1's customer_card → UI shape."""
    masked = (raw.get("card_number") or "")
    digits = [c for c in masked if c.isdigit()]
    last4 = "".join(digits[-4:]) if len(digits) >= 4 else ""
    type_id = raw.get("card_type_id") or 0
    try:
        type_id_int = int(type_id)
    except (TypeError, ValueError):
        type_id_int = 0
    # Prefer the live mapping from Vergent; fall back to our static table.
    _load_card_types()
    brand = (_card_types_by_id or {}).get(type_id_int) or _CARD_TYPE_NAMES.get(type_id_int, "Card")
    return {
        "id": raw.get("id"),
        "brand": brand,
        "last4": last4,
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

    # Log full list so we can compare against the Vergent admin UI and
    # see whether our PostCustomerCard outputs are actually persisted.
    summary = [
        {
            "id": c.get("id"),
            "type_id": c.get("card_type_id"),
            "holder": c.get("card_holder"),
            "last4": "".join(ch for ch in (c.get("card_number") or "") if ch.isdigit())[-4:],
            "is_existing": c.get("is_existing"),
            "is_active": c.get("is_active"),
            "CardProcessor": c.get("CardProcessor"),
            "card_processor_type": c.get("card_processor_type"),
        }
        for c in body if isinstance(c, dict)
    ]
    log.info("GetCustomerCards cid=%s count=%s cards=%s", cid, len(summary), summary)

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
    zip_code = "".join(ch for ch in (body.get("zip") or "") if ch.isdigit())[:9]
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
    if not (5 <= len(zip_code) <= 9):
        return _json_response(400, {"error": "zip_invalid"})

    card_type = (body.get("cardType") or _detect_card_type(pan)).strip() or "Other"
    card_type_id = _vergent_card_type_id(card_type)
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
    # Vergent's PostCustomerCard accepts full card data and tokenizes
    # via Repay internally — but only if we tell it which processor
    # to use. Earlier submissions without card_processor_type landed
    # with CardProcessor="None" (saved record, not chargeable, hidden
    # in the admin UI). Sending processor type 1 + billing_zip_code
    # matches what Vergent's own admin form submits.
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
        "billing_zip_code": zip_code,
        "card_processor_type": 1,  # Repay on our tenant; confirmed in logs.
    }

    status, resp, raw = _v1_request("POST", "/V1/PostCustomerCard", body=v1_body)

    if status not in (200, 201):
        # Flatten newlines so CloudWatch doesn't split the multi-line
        # Vergent error body into separate log events (which makes the
        # tail truncate before we see the actual error).
        flat_raw = (raw or "").replace("\n", " ").replace("\r", " ")
        redacted = dict(v1_body)
        redacted["card_number"] = f"****{last4}"
        redacted["ccv"] = "***"
        log.warning("PostCustomerCard upstream status=%s body=%s raw=%s",
                    status, redacted, flat_raw[:1500])
        return _json_response(502, {"error": "upstream_unavailable"})

    # v1's success response can be empty {} or carry the new card id;
    # we treat any 200/201 as success and look for 'Errors' to detect
    # in-band failures.
    if isinstance(resp, dict) and resp.get("Errors"):
        log.warning("PostCustomerCard returned errors cid=%s last4=%s errors=%s",
                    cid, last4, resp.get("Errors"))
        return _json_response(200, {"success": False, "error": "card_declined"})

    new_card_id = resp.get("id") if isinstance(resp, dict) else None
    # Log everything useful about the outcome so we can see whether
    # Vergent actually wired the card to Repay. Fields of interest:
    # is_existing, is_active, card_processor_type, CardProcessor.
    debug_flags = {}
    if isinstance(resp, dict):
        for k in ("is_existing", "is_active", "card_processor_type", "CardProcessor", "status", "card_guid"):
            if k in resp:
                debug_flags[k] = resp.get(k)
    log.info("add card success cid=%s last4=%s new_card_id=%s flags=%s",
             cid, last4, new_card_id, debug_flags)

    # Verify the card shows up on GetCustomerCards. If it doesn't,
    # Vergent accepted our POST but didn't actually register the card
    # for charging (CardProcessor="None" observed on plain
    # PostCustomerCard calls). Logs make it obvious next time.
    st_v, verify_body, _raw = _v1_request("GET", f"/V1/GetCustomerCards?custId={cid}")
    if st_v == 200 and isinstance(verify_body, list):
        found = any(
            isinstance(c, dict) and str(c.get("id")) == str(new_card_id)
            for c in verify_body
        )
        log.info("add card verify cid=%s new_card_id=%s in_list=%s list_count=%s",
                 cid, new_card_id, found, len(verify_body))
    else:
        log.warning("add card verify failed st=%s", st_v)

    return _json_response(200, {
        "success": True,
        "last4": last4,
        "brand": card_type,
        "cardId": new_card_id,
    })


def _extract_last4(candidates) -> str:
    """Given any string-ish, pull the trailing 4 digits. Returns '' if
    fewer than 4 digits are present anywhere in the string."""
    for c in candidates:
        if not c:
            continue
        digits = [ch for ch in str(c) if ch.isdigit()]
        if len(digits) >= 4:
            return "".join(digits[-4:])
    return ""


def _shape_bank_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Vergent v1 customer_bank → UI shape.

    Field names are inconsistent across Vergent's v1 surfaces so we
    check every variant we've seen before giving up.
    """
    last4 = _extract_last4([
        raw.get("account_number"), raw.get("AccountNumber"),
        raw.get("account_number_masked"), raw.get("AccountNumberMasked"),
        raw.get("MaskedAccountNumber"), raw.get("AcctLast4"),
        raw.get("last4"), raw.get("Last4"),
        raw.get("AccountNum"),
    ])
    type_id = raw.get("account_type_id") or raw.get("AccountTypeId") or raw.get("type_id") or 0
    try:
        type_id_int = int(type_id) if type_id not in (None, "") else 0
    except (TypeError, ValueError):
        type_id_int = 0
    type_name = {1: "Checking", 2: "Savings"}.get(type_id_int, "Checking")
    return {
        "id": raw.get("id") or raw.get("Id") or raw.get("bank_id"),
        "name": (raw.get("bank_name") or raw.get("name") or raw.get("Name")
                 or raw.get("BankName") or "Bank"),
        "last4": last4,
        "accountType": type_name,
        "isPrimary": bool(raw.get("is_primary") or raw.get("IsPrimary")),
    }


def get_my_banks(event: Dict[str, Any]) -> Dict[str, Any]:
    """List the signed-in customer's saved bank accounts (ACH) via v1.

    Primary source: /api/V1/GetCustomerBanks?custId=<cid>. If that
    returns an empty list, fall back to the bank embedded on the
    active loan (LoanDetail.AccountNum). Vergent originations usually
    capture the customer's bank on the loan itself, and that field is
    always a masked string we can show.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(200, {"banks": []})

    status, body, raw = _v1_request("GET", f"/V1/GetCustomerBanks?custId={cid}")
    shaped: list = []
    if status == 200 and isinstance(body, list):
        shaped = [_shape_bank_v1(b) for b in body if isinstance(b, dict)]
        # One-shot probe so we can see Vergent's actual field names.
        if body:
            first = body[0] if isinstance(body[0], dict) else {}
            log.info("GetCustomerBanks probe cid=%s count=%s first_keys=%s",
                     cid, len(body), sorted(first.keys()))
    else:
        log.warning("GetCustomerBanks status=%s raw=%s", status, (raw or "")[:300])

    # Fallback: bank on the active loan record (LoanDetail.AccountNum).
    # Harut's loan carries this even when GetCustomerBanks returns [].
    if not shaped:
        fallback = _fallback_bank_from_loan(cid)
        if fallback:
            shaped = [fallback]

    return _json_response(200, {"banks": shaped})


def _fallback_bank_from_loan(cid: str) -> Optional[Dict[str, Any]]:
    """Pull a minimal bank record from the active loan's LoanDetail.

    We don't get a real bank id from the loan detail; use the header's
    PaymentBankAccountId (if present) as an id stand-in so the UI
    radio-group works. Server-side payment validation re-checks
    against GetCustomerBanks, so a synthetic id here only affects
    display.
    """
    status, body = _v1_get(f"/V1/{cid}/loans")
    if status != 200 or not isinstance(body, list) or not body:
        return None
    for rec in body:
        if not isinstance(rec, dict):
            continue
        detail = rec.get("LoanDetail") if isinstance(rec.get("LoanDetail"), dict) else {}
        hdr = rec.get("LoanHeader") if isinstance(rec.get("LoanHeader"), dict) else {}
        account = detail.get("AccountNum") or detail.get("accountNum")
        if not account:
            continue
        last4 = _extract_last4([account])
        if not last4:
            continue
        return {
            "id": hdr.get("PaymentBankAccountId") or detail.get("BankAccountId") or 0,
            "name": detail.get("Lender") or detail.get("BankName") or "Bank on file",
            "last4": last4,
            "accountType": "Checking",
            "isPrimary": True,
        }
    return None


def post_payment(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/my-payment — charge a card OR debit a bank account.

    Body:
      { method: 'card' | 'bank',
        loanId, amount,
        cardId  (when method=card),
        bankId  (when method=bank),
        idempotencyKey }

    Both flows use v1 PostCustomerLoanPayment — v1 auths with the
    service Token header and takes customerId-free context (loan id
    + payment method id). No customer JWT required.
    """
    claims = _claims(event)
    cid = _customer_id(claims)
    if not cid:
        return _json_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _json_response(400, {"error": "bad_body"})

    pay_method = (body.get("method") or "card").lower()
    loan_id = body.get("loanId")
    amount = body.get("amount")

    if loan_id is None or amount is None:
        return _json_response(400, {"error": "missing_fields"})
    try:
        amount_num = float(amount)
    except (TypeError, ValueError):
        return _json_response(400, {"error": "amount_invalid"})
    if amount_num <= 0:
        return _json_response(400, {"error": "amount_invalid"})

    # Ownership + payoff guard via v1 (same pattern as before).
    loan = _fetch_active_loan(cid)
    if not loan or str(loan.get("id")) != str(loan_id):
        status_ok, raw_loans = _v1_get(f"/V1/{cid}/loans")
        found = None
        if status_ok == 200 and isinstance(raw_loans, list):
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

    store_id = loan.get("storeId") or 0
    hdr_id = int(loan.get("id")) if loan.get("id") else 0

    # Vergent v1 PostCustomerLoanPayment body shape (documented):
    #   CompanyId, StoreId, UserId, HeaderId, PaymentDate, PaymentAmount,
    #   PaymentMethod (object: Type + reference fields depending on type)
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if pay_method == "card":
        card_id = body.get("cardId")
        if card_id is None:
            return _json_response(400, {"error": "missing_fields"})
        # Ownership: confirm the cardId is in the customer's saved cards.
        st_c, cards_body, _ = _v1_request("GET", f"/V1/GetCustomerCards?custId={cid}")
        if st_c != 200 or not isinstance(cards_body, list):
            return _json_response(502, {"error": "upstream_unavailable"})
        card = next(
            (c for c in cards_body if isinstance(c, dict) and str(c.get("id")) == str(card_id)),
            None,
        )
        if not card:
            return _json_response(403, {"error": "card_not_yours"})
        last4 = "".join(ch for ch in (card.get("card_number") or "") if ch.isdigit())[-4:]
        method_obj = {"Type": "Card", "CardId": int(card_id)}
    elif pay_method == "bank":
        bank_id = body.get("bankId")
        if bank_id is None:
            return _json_response(400, {"error": "missing_fields"})
        # Ownership: confirm the bankId is in the customer's saved banks.
        st_b, banks_body, _ = _v1_request("GET", f"/V1/GetCustomerBanks?custId={cid}")
        if st_b != 200 or not isinstance(banks_body, list):
            return _json_response(502, {"error": "upstream_unavailable"})
        bank = next(
            (b for b in banks_body if isinstance(b, dict) and str(b.get("id")) == str(bank_id)),
            None,
        )
        if not bank:
            return _json_response(403, {"error": "bank_not_yours"})
        last4 = "".join(ch for ch in (bank.get("account_number") or "") if ch.isdigit())[-4:]
        method_obj = {"Type": "ACH", "BankId": int(bank_id)}
    else:
        return _json_response(400, {"error": "method_invalid"})

    charge_body = {
        "CompanyId": VERGENT_COMPANY_ID,
        "StoreId": int(store_id) if store_id else 0,
        "HeaderId": hdr_id,
        "PaymentDate": now_iso,
        "PaymentAmount": round(amount_num, 2),
        "PaymentMethod": method_obj,
    }

    log.info("payment attempt cid=%s method=%s loan_id=%s last4=%s amount=%s",
             cid, pay_method, loan_id, last4, amount_num)

    status, charge, raw = _v1_request("POST", "/V1/PostCustomerLoanPayment", body=charge_body)

    if status not in (200, 201):
        log.warning("payment upstream status=%s raw=%s", status, (raw or "")[:300])
        return _json_response(502, {"error": "upstream_unavailable"})

    if isinstance(charge, dict) and charge.get("Errors"):
        log.warning("payment declined cid=%s loan_id=%s errors=%s",
                    cid, loan_id, charge.get("Errors"))
        return _json_response(200, {"success": False, "error": "card_declined"})

    # Re-fetch the loan so we can tell the UI the new balance.
    refreshed = _fetch_active_loan(cid)
    new_balance = refreshed.get("balance") if refreshed else None

    trans_id = charge.get("TransactionId") if isinstance(charge, dict) else None
    confirmation_id = str(trans_id) if trans_id else now_iso

    log.info("payment success cid=%s method=%s loan_id=%s last4=%s amount=%s trans=%s new_balance=%s",
             cid, pay_method, loan_id, last4, amount_num, trans_id, new_balance)

    return _json_response(200, {
        "success": True,
        "confirmationId": confirmation_id,
        "transactionId": trans_id,
        "amount": round(amount_num, 2),
        "last4": last4,
        "paymentMethod": pay_method,
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
        if path.endswith("/my-banks") and method == "GET":
            return get_my_banks(event)
        if path.endswith("/my-payment/loan-summary") and method == "GET":
            return get_loan_summary(event)
        if path.endswith("/my-payment") and method == "POST":
            return post_payment(event)

        return _json_response(404, {"error": "not_found", "path": path})
    except Exception as exc:
        log.exception("payments handler unexpected error: %s", exc)
        return _json_response(500, {"error": "internal_error"})
