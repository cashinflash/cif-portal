"""POST /api/search — Vergent customer lookup (pre-login, unauthenticated).

Hits V2 Public API `POST /api/CustomerPortal/Customer/Search`, then
narrows the result client-side by first + last name (defense in depth
on top of Vergent's server-side match on SSN + DOB). Phone is optional
and passed through only to reduce Vergent-side false positives.
Returns:

  { match: "single", vergentCustomerId: "...", email: "...", hasPortalAccount: bool }
  { match: "none" }
  { match: "multiple" }
"""

import logging
import os
import boto3
from botocore.exceptions import ClientError

import vergent
from responses import ok, error, parse_body

_log = logging.getLogger()
_log.setLevel(logging.INFO)


_cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")


def lambda_handler(event, context):
    body = parse_body(event)
    required = ["firstName", "lastName", "dob", "idNumber"]
    missing = [k for k in required if not body.get(k)]
    if missing:
        return error(f"Missing fields: {', '.join(missing)}", status=400)

    phone_digits = "".join(c for c in (body.get("phone") or "") if c.isdigit())
    # SSN: strip dashes and spaces. Both '123-45-6789' and '123456789'
    # arrive at Vergent the same way.
    id_digits = "".join(c for c in body["idNumber"] if c.isdigit())
    birth_date_iso = _to_iso_datetime(body["dob"])  # YYYY-MM-DD -> full ISO

    try:
        # userType=1 is consumer (verified by probe 2026-04-18).
        # userType=0 and userType=2 both trigger "Bussiness name" validation.
        matches = vergent.customer_search(
            first_name=body["firstName"].strip(),
            last_name=body["lastName"].strip(),
            birth_date_iso=birth_date_iso,
            phone_number=phone_digits,
            id_number=id_digits,
            user_type=1,
        )
    except Exception as e:
        return error(f"Vergent lookup failed: {e}", status=502)

    first = body["firstName"].strip().lower()
    last = body["lastName"].strip().lower()
    verified = [m for m in matches if _name_matches(m, first, last)]

    if not verified:
        return ok({"match": "none"})
    if len(verified) > 1:
        return ok({"match": "multiple"})

    customer = verified[0]
    vergent_customer_id = str(customer.get("customerId") or "")
    email = customer.get("email") or ""
    first_name = customer.get("firstName") or body["firstName"]
    last_name = customer.get("lastName") or body["lastName"]

    return ok({
        "match": "single",
        "vergentCustomerId": vergent_customer_id,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "hasPortalAccount": _cognito_user_exists(email, vergent_customer_id),
    })


def _to_iso_datetime(ymd: str) -> str:
    """Convert 'YYYY-MM-DD' to 'YYYY-MM-DDT00:00:00Z' for Vergent's shape.

    Already-ISO inputs pass through unchanged.
    """
    ymd = (ymd or "").strip()
    if not ymd:
        return ""
    if "T" in ymd:
        return ymd
    return f"{ymd}T00:00:00Z"


def _name_matches(customer: dict, first: str, last: str) -> bool:
    first_v = (customer.get("firstName") or "").strip().lower()
    last_v = (customer.get("lastName") or "").strip().lower()
    return first_v == first and last_v == last


def _cognito_user_exists(email: str, vergent_customer_id: str) -> bool:
    """Return True if either identifier is already tied to a portal account.

    Cognito's ListUsers Filter only supports a fixed set of standard attrs —
    custom:vergentCustomerId is NOT filterable. So we do:
      1. Fast path: filter by email (Cognito-native, O(1))
      2. Slow path: paginate the pool and match vergentCustomerId client-side
    Once user count outgrows ~1000, move path 2 to a DynamoDB index.
    """
    if not _POOL_ID:
        return False
    email = (email or "").strip().lower()
    vcid  = (vergent_customer_id or "").strip()
    if not email and not vcid:
        return False

    # Path 1 — email filter
    if email:
        try:
            resp = _cognito.list_users(
                UserPoolId=_POOL_ID,
                Filter=f'email = "{email}"',
                Limit=1,
            )
            if resp.get("Users"):
                return True
        except ClientError as e:
            _log.warning("cognito list_users by email failed: %s", e)

    # Path 2 — paginated scan for matching custom attribute
    if not vcid:
        return False
    pagination_token = None
    scanned = 0
    MAX_SCAN = 5000
    while scanned < MAX_SCAN:
        kwargs = {"UserPoolId": _POOL_ID, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = _cognito.list_users(**kwargs)
        except ClientError as e:
            _log.warning("cognito list_users scan failed: %s", e)
            return False
        for u in resp.get("Users", []):
            for a in u.get("Attributes", []):
                if a.get("Name") == "custom:vergentCustomerId" and a.get("Value") == vcid:
                    return True
        scanned += len(resp.get("Users", []))
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    return False
