"""Plaid integration — link customer bank accounts.

Customer flow:
  1. Frontend hits POST /api/plaid/link-token to get a short-lived
     Link token.
  2. Plaid Link iframe opens, customer auths with their bank.
  3. On success, frontend POSTs the public_token to
     /api/plaid/exchange.
  4. Backend exchanges public_token → long-lived access_token,
     stores it in DynamoDB keyed by (customerId, itemId).
  5. Customer sees the connected institution + masked account on
     the Profile page; can tap Disconnect any time.

The stored access_token is the artifact underwriting needs: any
later asset-report / auth / transactions pull happens server-side
without re-prompting the customer.

Secret fields (at PLAID_SECRET_ARN):
  clientId   — from dashboard.plaid.com Team Settings → Keys
  secret     — production / development / sandbox secret
  env        — "production" | "development" | "sandbox"
                (controls which Plaid host we hit)

Plaid API reference: https://plaid.com/docs/api/
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()

_secrets = boto3.client(
    "secretsmanager",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
_dynamo = boto3.client(
    "dynamodb",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)

_creds_cache: Optional[Dict[str, str]] = None

PLAID_ITEMS_TABLE = os.environ.get(
    "PLAID_ITEMS_TABLE", "cif-portal-plaid-items-dev"
)
CLIENT_NAME = "Cash in Flash"
PRODUCTS = ["auth", "identity", "transactions"]
COUNTRY_CODES = ["US"]
LANGUAGE = "en"
HTTP_TIMEOUT = 12  # seconds


# ─────────────────────────────────────────
# Plaid API plumbing
# ─────────────────────────────────────────

def _load_creds() -> Optional[Dict[str, str]]:
    """Fetch + cache {clientId, secret, env} from Secrets Manager."""
    global _creds_cache
    if _creds_cache:
        return _creds_cache
    arn = os.environ.get("PLAID_SECRET_ARN") or ""
    if not arn:
        log.warning("PLAID_SECRET_ARN not set")
        return None
    try:
        resp = _secrets.get_secret_value(SecretId=arn)
    except ClientError as e:
        log.warning("plaid secret read failed: %s",
                    e.response.get("Error", {}).get("Code"))
        return None
    p = json.loads(resp["SecretString"])
    client_id = p.get("clientId") or p.get("client_id") or p.get("PLAID_CLIENT_ID")
    secret = p.get("secret") or p.get("PLAID_SECRET")
    env = (p.get("env") or p.get("environment") or p.get("PLAID_ENV") or "production").strip().lower()
    if not (client_id and secret):
        log.warning("plaid secret missing fields clientId=%s secret=%s",
                    bool(client_id), bool(secret))
        return None
    _creds_cache = {"clientId": client_id, "secret": secret, "env": env}
    return _creds_cache


def _api_host(env: str) -> str:
    return f"https://{env}.plaid.com"


def _plaid_post(path: str, body: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]], str]:
    """Post a JSON body to Plaid. Auto-injects client_id + secret.
    Returns (status, parsed_json or None, raw_text)."""
    creds = _load_creds()
    if not creds:
        return 0, None, "credentials_unavailable"
    payload = dict(body)
    payload["client_id"] = creds["clientId"]
    payload["secret"] = creds["secret"]
    url = f"{_api_host(creds['env'])}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "cif-portal/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.getcode(), _safe_json(raw), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        return e.code, _safe_json(raw), raw
    except urllib.error.URLError as e:
        log.warning("plaid network error path=%s err=%s", path, e)
        return 0, None, str(e)
    except Exception as e:
        log.warning("plaid unexpected error path=%s err=%s", path, type(e).__name__)
        return 0, None, type(e).__name__


def _safe_json(raw: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(raw or "")
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────
# DDB helpers — store/list/delete connections
# ─────────────────────────────────────────

def _put_connection(cid: str, item_id: str, access_token: str,
                    institution_name: str, institution_id: str,
                    account_mask: str, account_subtype: str) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    item = {
        "customerId": {"S": str(cid)},
        "itemId": {"S": str(item_id)},
        "accessToken": {"S": access_token},
        "institutionName": {"S": institution_name or "Bank"},
        "institutionId": {"S": institution_id or ""},
        "accountMask": {"S": account_mask or ""},
        "accountSubtype": {"S": account_subtype or ""},
        "linkedAt": {"S": now},
    }
    _dynamo.put_item(TableName=PLAID_ITEMS_TABLE, Item=item)


def _list_connections(cid: str) -> List[Dict[str, Any]]:
    resp = _dynamo.query(
        TableName=PLAID_ITEMS_TABLE,
        KeyConditionExpression="customerId = :c",
        ExpressionAttributeValues={":c": {"S": str(cid)}},
    )
    out: List[Dict[str, Any]] = []
    for it in resp.get("Items") or []:
        out.append({
            "itemId": it.get("itemId", {}).get("S", ""),
            "institutionName": it.get("institutionName", {}).get("S", "Bank"),
            "institutionId": it.get("institutionId", {}).get("S", ""),
            "accountMask": it.get("accountMask", {}).get("S", ""),
            "accountSubtype": it.get("accountSubtype", {}).get("S", ""),
            "linkedAt": it.get("linkedAt", {}).get("S", ""),
        })
    out.sort(key=lambda x: x.get("linkedAt", ""), reverse=True)
    return out


def _get_access_token(cid: str, item_id: str) -> Optional[str]:
    resp = _dynamo.get_item(
        TableName=PLAID_ITEMS_TABLE,
        Key={
            "customerId": {"S": str(cid)},
            "itemId": {"S": str(item_id)},
        },
    )
    item = resp.get("Item")
    if not item:
        return None
    return item.get("accessToken", {}).get("S") or None


def _delete_connection(cid: str, item_id: str) -> None:
    _dynamo.delete_item(
        TableName=PLAID_ITEMS_TABLE,
        Key={
            "customerId": {"S": str(cid)},
            "itemId": {"S": str(item_id)},
        },
    )


# ─────────────────────────────────────────
# Helpers shared across handlers
# ─────────────────────────────────────────

def _customer_id_from_event(event: Dict[str, Any]) -> Optional[str]:
    """Pull custom:vergentCustomerId from the JWT on the request."""
    claims = (((event.get("requestContext") or {}).get("authorizer") or {})
              .get("jwt", {}).get("claims") or {})
    if not claims:
        # Fallback for some local-test event shapes
        claims = ((event.get("requestContext") or {}).get("authorizer") or {})
    cid = (
        claims.get("custom:vergentCustomerId")
        or claims.get("vergentCustomerId")
    )
    if cid:
        return str(cid).strip()
    return None


def _json_response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        },
        "body": json.dumps(body),
    }


# ─────────────────────────────────────────
# Route handlers
# ─────────────────────────────────────────

def link_token(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/plaid/link-token — mint a short-lived Link token.

    Plaid Link runs entirely in the customer's browser; the link
    token authenticates that session as belonging to this customer
    on our Plaid account. No long-lived data leaves Plaid here.
    """
    cid = _customer_id_from_event(event)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})

    body = {
        "client_name": CLIENT_NAME,
        "country_codes": COUNTRY_CODES,
        "language": LANGUAGE,
        "products": PRODUCTS,
        "user": {"client_user_id": str(cid)},
    }
    status, parsed, raw = _plaid_post("/link/token/create", body)
    if status != 200 or not isinstance(parsed, dict):
        log.warning("plaid link-token-create non-200 cid=%s status=%s body=%r",
                    cid, status, (raw or "")[:300])
        return _json_response(502, {
            "ok": False,
            "error": "plaid_error",
            "upstreamStatus": status,
            "upstreamBody": (raw or "")[:600],
        })
    token = parsed.get("link_token")
    expiration = parsed.get("expiration")
    if not token:
        return _json_response(502, {"ok": False, "error": "missing_link_token"})
    return _json_response(200, {
        "ok": True,
        "linkToken": token,
        "expiration": expiration,
    })


def exchange(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/plaid/exchange — exchange public_token for
    access_token and persist the connection.

    Body: {
      "publicToken": "<Plaid public_token from Link onSuccess>",
      "metadata": { Plaid Link metadata blob — institution + accounts }
    }
    """
    cid = _customer_id_from_event(event)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        body = {}
    public_token = (body.get("publicToken") or "").strip()
    metadata = body.get("metadata") or {}
    if not public_token:
        return _json_response(400, {"ok": False, "error": "missing_publicToken"})

    status, parsed, raw = _plaid_post(
        "/item/public_token/exchange",
        {"public_token": public_token},
    )
    if status != 200 or not isinstance(parsed, dict):
        log.warning("plaid exchange non-200 cid=%s status=%s body=%r",
                    cid, status, (raw or "")[:300])
        return _json_response(502, {
            "ok": False,
            "error": "plaid_error",
            "upstreamStatus": status,
            "upstreamBody": (raw or "")[:600],
        })
    access_token = parsed.get("access_token")
    item_id = parsed.get("item_id")
    if not (access_token and item_id):
        return _json_response(502, {"ok": False, "error": "missing_token_or_item"})

    institution = metadata.get("institution") or {}
    institution_name = (institution.get("name") or "").strip() or "Bank"
    institution_id = institution.get("institution_id") or ""
    accounts = metadata.get("accounts") or []
    primary = accounts[0] if accounts else {}
    account_mask = (primary.get("mask") or "").strip()
    account_subtype = (primary.get("subtype") or primary.get("type") or "").strip()

    try:
        _put_connection(
            cid=cid,
            item_id=item_id,
            access_token=access_token,
            institution_name=institution_name,
            institution_id=institution_id,
            account_mask=account_mask,
            account_subtype=account_subtype,
        )
    except ClientError as e:
        log.error("plaid DDB put failed cid=%s err=%s",
                  cid, e.response.get("Error", {}).get("Code"))
        return _json_response(500, {"ok": False, "error": "store_failed"})

    log.info("plaid linked cid=%s item=%s institution=%s mask=%s",
             cid, item_id, institution_name, account_mask)
    return _json_response(200, {
        "ok": True,
        "connection": {
            "itemId": item_id,
            "institutionName": institution_name,
            "institutionId": institution_id,
            "accountMask": account_mask,
            "accountSubtype": account_subtype,
        },
    })


def list_connections(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/plaid/connections — list this customer's linked
    bank accounts (no access_token leaks to the client)."""
    cid = _customer_id_from_event(event)
    if not cid:
        return _json_response(200, {"connections": []})
    try:
        return _json_response(200, {"connections": _list_connections(cid)})
    except ClientError as e:
        log.warning("plaid DDB query failed cid=%s err=%s",
                    cid, e.response.get("Error", {}).get("Code"))
        return _json_response(200, {"connections": []})


def disconnect(event: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    """DELETE /api/plaid/connections/{itemId} — revoke at Plaid +
    drop the row in DDB. Ownership enforced by the partition key
    being the JWT's customerId."""
    cid = _customer_id_from_event(event)
    if not cid:
        return _json_response(401, {"ok": False, "error": "no_customer_id"})
    if not item_id:
        return _json_response(400, {"ok": False, "error": "missing_itemId"})

    access_token = _get_access_token(cid, item_id)
    if not access_token:
        # Already disconnected (or never owned by this customer).
        return _json_response(404, {"ok": False, "error": "not_found"})

    status, _parsed, raw = _plaid_post(
        "/item/remove", {"access_token": access_token},
    )
    if status not in (200, 204):
        log.warning("plaid item/remove non-2xx cid=%s item=%s status=%s body=%r",
                    cid, item_id, status, (raw or "")[:300])
        # Still drop the DDB row — the customer's intent is to
        # disconnect; Plaid will eventually expire the item even
        # if the explicit revoke RPC failed.

    try:
        _delete_connection(cid, item_id)
    except ClientError as e:
        log.error("plaid DDB delete failed cid=%s item=%s err=%s",
                  cid, item_id, e.response.get("Error", {}).get("Code"))
        return _json_response(500, {"ok": False, "error": "delete_failed"})

    log.info("plaid disconnected cid=%s item=%s", cid, item_id)
    return _json_response(200, {"ok": True})


# ─────────────────────────────────────────
# Admin endpoints (cif-admin Cognito group)
# Used by cif-dashboard's "Portal Bank Links" sub-tab to list
# every customer who has linked a bank via the portal, plus
# detail / re-pull data on demand. Auth gate is a group check
# on the JWT — separate from the customer endpoints above.
# ─────────────────────────────────────────

ADMIN_GROUP_NAME = "cif-admin"


def _claims_from_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """JWT claims live under requestContext.authorizer.jwt.claims
    on HttpApi events with a JWT authorizer attached."""
    return (((event.get("requestContext") or {}).get("authorizer") or {})
            .get("jwt", {}).get("claims") or {})


def _require_admin_group(claims: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return None if the caller is in the cif-admin Cognito
    group; otherwise return a 403 response dict the caller
    should bubble up.

    cognito:groups can come through several shapes depending on
    the auth flow:
      - list:   ["cif-admin", "user"]
      - csv:    "cif-admin,user"
      - bracketed: "[cif-admin user]"
    Normalize all three.
    """
    groups_raw = claims.get("cognito:groups") or claims.get("groups") or []
    if isinstance(groups_raw, str):
        cleaned = groups_raw.strip("[]").replace(",", " ")
        groups = [g.strip() for g in cleaned.split() if g.strip()]
    elif isinstance(groups_raw, list):
        groups = [str(g).strip() for g in groups_raw if g]
    else:
        groups = []
    if ADMIN_GROUP_NAME not in groups:
        log.info("admin gate denied caller_groups=%s required=%s",
                 groups, ADMIN_GROUP_NAME)
        return _json_response(403, {"ok": False, "error": "admin_required"})
    return None


def _fetch_vergent_profile(cid: str) -> Dict[str, str]:
    """Pull a thin name+email+phone-last-4 profile from Vergent.
    Lazy-imports loans._v1_get to avoid a circular module-load
    at boot."""
    from handlers import loans  # noqa: WPS433 — lazy on purpose
    out = {"firstName": "", "lastName": "", "email": "", "phoneLast4": ""}
    try:
        status, body = loans._v1_get(f"/V1/GetCustomer/{cid}")
    except Exception as e:
        log.info("admin vergent-profile fetch err cid=%s err=%s",
                 cid, type(e).__name__)
        return out
    if status != 200 or not isinstance(body, dict):
        return out
    out["firstName"] = str(body.get("FirstName") or "").strip()
    out["lastName"] = str(body.get("LastName") or "").strip()
    out["email"] = str(body.get("EmailAddr") or "").strip()
    # Try v1 GetCustomerData for the primary phone
    try:
        s2, data = loans._v1_get(f"/V1/GetCustomerData/{cid}")
        if s2 == 200 and isinstance(data, dict):
            phones = data.get("custPhones") or []
            primary = next(
                (p for p in phones if isinstance(p, dict) and p.get("is_primary")),
                next((p for p in phones if isinstance(p, dict)), None),
            )
            if primary:
                num = str(primary.get("number") or "")
                if len(num) >= 4:
                    out["phoneLast4"] = num[-4:]
    except Exception:
        pass
    return out


def _scan_all_items() -> List[Dict[str, Any]]:
    """Scan the entire Plaid items table. Fine for the small
    customer count we're at. Replace with a GSI-backed query
    once we cross ~5k connected customers."""
    out: List[Dict[str, Any]] = []
    last_key = None
    while True:
        kwargs: Dict[str, Any] = {"TableName": PLAID_ITEMS_TABLE}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _dynamo.scan(**kwargs)
        out.extend(resp.get("Items") or [])
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return out


def list_admin_customers(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /api/admin/plaid/customers — admin-only listing of
    every customer who has linked a bank via the portal,
    hydrated with Vergent profile (name + email + phone last 4).

    Optional `?search=jane` filters on name / email / customerId
    (substring, case-insensitive)."""
    claims = _claims_from_event(event)
    err = _require_admin_group(claims)
    if err:
        return err

    qs = event.get("queryStringParameters") or {}
    search = ((qs or {}).get("search") or "").strip().lower()

    # Pull every Plaid Item row from DDB and group by customerId.
    raw = _scan_all_items()
    by_cid: Dict[str, List[Dict[str, Any]]] = {}
    for it in raw:
        cid = (it.get("customerId") or {}).get("S") or ""
        if not cid:
            continue
        by_cid.setdefault(cid, []).append({
            "itemId": (it.get("itemId") or {}).get("S") or "",
            "institutionName": (it.get("institutionName") or {}).get("S") or "Bank",
            "institutionId": (it.get("institutionId") or {}).get("S") or "",
            "accountMask": (it.get("accountMask") or {}).get("S") or "",
            "accountSubtype": (it.get("accountSubtype") or {}).get("S") or "",
            "linkedAt": (it.get("linkedAt") or {}).get("S") or "",
        })

    # Fan out Vergent profile fetches in parallel — typical CIF
    # customer count is small (<100 portal-linked at MVP), so an
    # 8-wide pool is fine.
    profiles: Dict[str, Dict[str, str]] = {}
    if by_cid:
        from concurrent.futures import ThreadPoolExecutor as _Pool
        with _Pool(max_workers=min(8, len(by_cid))) as ex:
            futures = {ex.submit(_fetch_vergent_profile, cid): cid
                       for cid in by_cid.keys()}
            for fut in futures:
                profiles[futures[fut]] = fut.result()

    # Flatten into one row per (customer, item) pair.
    out: List[Dict[str, Any]] = []
    for cid, items in by_cid.items():
        prof = profiles.get(cid, {})
        full_name = (prof.get("firstName", "") + " " + prof.get("lastName", "")).strip()
        for item in items:
            out.append({
                "customerId": cid,
                "customerName": full_name,
                "customerEmail": prof.get("email", ""),
                "customerPhoneLast4": prof.get("phoneLast4", ""),
                **item,
            })

    if search:
        out = [r for r in out if (
            search in (r.get("customerName") or "").lower()
            or search in (r.get("customerEmail") or "").lower()
            or search in (r.get("customerId") or "").lower()
            or search in (r.get("institutionName") or "").lower()
        )]

    out.sort(key=lambda r: r.get("linkedAt") or "", reverse=True)
    log.info("admin list-customers caller_groups=%s rows=%d",
             claims.get("cognito:groups"), len(out))
    return _json_response(200, {"customers": out})


def get_admin_customer(event: Dict[str, Any], cid: str) -> Dict[str, Any]:
    """GET /api/admin/plaid/customer/{cid} — full detail for one
    customer. Returns Vergent profile + every Plaid Item, with a
    fresh /accounts/get pull per Item so admins see all the
    accounts under each link, not just the primary mask we
    cached at link-time."""
    claims = _claims_from_event(event)
    err = _require_admin_group(claims)
    if err:
        return err
    if not cid:
        return _json_response(400, {"ok": False, "error": "missing_cid"})

    # All items for this customer.
    try:
        resp = _dynamo.query(
            TableName=PLAID_ITEMS_TABLE,
            KeyConditionExpression="customerId = :c",
            ExpressionAttributeValues={":c": {"S": str(cid)}},
        )
    except ClientError as e:
        log.warning("admin DDB query err cid=%s err=%s",
                    cid, e.response.get("Error", {}).get("Code"))
        return _json_response(502, {"ok": False, "error": "db_error"})
    raw_items = resp.get("Items") or []
    if not raw_items:
        return _json_response(404, {"ok": False, "error": "no_connections"})

    profile = _fetch_vergent_profile(cid)

    items: List[Dict[str, Any]] = []
    for it in raw_items:
        item_id = (it.get("itemId") or {}).get("S") or ""
        access_token = (it.get("accessToken") or {}).get("S") or ""
        accounts: List[Dict[str, Any]] = []
        if access_token:
            try:
                a_status, a_parsed, _a_raw = _plaid_post(
                    "/accounts/get", {"access_token": access_token},
                )
                if a_status == 200 and isinstance(a_parsed, dict):
                    for acc in a_parsed.get("accounts") or []:
                        bal = acc.get("balances") or {}
                        accounts.append({
                            "accountId": acc.get("account_id"),
                            "name": acc.get("name"),
                            "officialName": acc.get("official_name"),
                            "mask": acc.get("mask"),
                            "type": acc.get("type"),
                            "subtype": acc.get("subtype"),
                            "currentBalance": bal.get("current"),
                            "availableBalance": bal.get("available"),
                            "currency": bal.get("iso_currency_code"),
                        })
                else:
                    log.info("admin /accounts/get non-200 item=%s status=%s",
                             item_id, a_status)
            except Exception as e:
                log.info("admin /accounts/get err item=%s err=%s",
                         item_id, type(e).__name__)
        items.append({
            "itemId": item_id,
            "institutionName": (it.get("institutionName") or {}).get("S") or "Bank",
            "institutionId": (it.get("institutionId") or {}).get("S") or "",
            "linkedAt": (it.get("linkedAt") or {}).get("S") or "",
            "accounts": accounts,
        })

    return _json_response(200, {
        "customerId": cid,
        "customerName": (profile.get("firstName", "") + " " + profile.get("lastName", "")).strip(),
        "customerEmail": profile.get("email", ""),
        "customerPhoneLast4": profile.get("phoneLast4", ""),
        "items": items,
    })
