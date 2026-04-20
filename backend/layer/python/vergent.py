"""Vergent V2 Public API client.

Targets the external Vergent gateway at
https://prod.apim.vergentlms.com/external/shared. Authentication is a
single static header `x-api-key: <key>`. No authenticate-then-use-token
flow — just one header on every request.

The x-api-key is loaded once per Lambda container from AWS Secrets
Manager (`cif-portal/vergent/credentials`, field `xApiKey`).

Endpoint paths used are from the Swagger definition at
https://prod.apim.vergentlms.com/external/shared/swagger/index.html —
specifically the `CustomerPortalCustomer` and related tags.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

import aws_secrets as _secrets

_BASE = os.environ.get(
    "VERGENT_BASE_URL",
    "https://prod.apim.vergentlms.com/external/shared",
)
_COMPANY_ID = os.environ.get("VERGENT_COMPANY_ID", "386")
_CREDS_SECRET = os.environ.get("VERGENT_CREDS_SECRET", "cif-portal/vergent/credentials")

_api_key: str | None = None


def _get_api_key() -> str:
    global _api_key
    if _api_key:
        return _api_key
    creds = _secrets.load(_CREDS_SECRET)
    key = creds.get("xApiKey") or ""
    if not key:
        raise RuntimeError("xApiKey missing from Vergent credentials secret")
    _api_key = key
    return key


def _request(method: str, path: str, *, body: dict | None = None) -> Any:
    url = f"{_BASE}{path}"
    headers = {
        "x-api-key": _get_api_key(),
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        # Swagger example uses this unusual content-type. application/json
        # also works in practice; starting strict with what the spec says.
        headers["Content-Type"] = "application/json-patch+json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        # Re-raise with body attached so callers can log useful detail
        detail = ""
        try:
            detail = (e.read() or b"").decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise RuntimeError(
            f"Vergent {method} {path} -> HTTP {e.code}: {detail or e.reason}"
        ) from e


# ────────── Customer lookup (pre-login) ──────────

def customer_search(*, first_name: str = "", last_name: str = "",
                    birth_date_iso: str = "", phone_number: str = "",
                    id_number: str = "", ein_number: str = "",
                    business_name: str = "", user_type: int = 0) -> list[dict]:
    """POST /api/CustomerPortal/Customer/Search — fuzzy customer lookup.

    birth_date_iso must be ISO 8601 datetime (YYYY-MM-DDTHH:MM:SSZ).
    Returns list of {customerId, firstName, lastName, customerType,
    mobileProfileId, isProspect, mobileNumbers}.
    """
    result = _request("POST", "/api/CustomerPortal/Customer/Search", body={
        "firstName": first_name,
        "lastName": last_name,
        "businessName": business_name,
        "birthDate": birth_date_iso,
        "phoneNumber": phone_number,
        "idNumber": id_number,
        "einNumber": ein_number,
        "userType": user_type,
    })
    if isinstance(result, list):
        return result
    return []


def customer_search_by_email(email: str) -> dict | None:
    """GET /api/CustomerPortal/Customer/SearchByEmail/{email}."""
    return _request("GET", f"/api/CustomerPortal/Customer/SearchByEmail/{email}")


# ────────── Post-login accessors (require customer-scoped auth we'll add later) ──────────

def customer_profile() -> dict:
    return _request("GET", "/api/CustomerPortal/Customer/Profile")


def customer_loans_full() -> dict:
    return _request("GET", "/api/CustomerPortal/Customer/Loans/Full")


def customer_loans_open() -> list[dict]:
    return _request("GET", "/api/CustomerPortal/Loans") or []


def loan_transactions(loan_id: int | str) -> list[dict]:
    return _request("GET", f"/api/CustomerPortal/Loans/{loan_id}/Transactions") or []


def loan_contracts_and_receipts(loan_id: int | str) -> list[dict]:
    return _request(
        "GET",
        f"/api/CustomerPortal/Loans/{loan_id}/Documents/ContractsAndReceipts",
    ) or []


def customer_documents() -> list[dict]:
    return _request("GET", "/api/CustomerPortal/Customer/Documents") or []
