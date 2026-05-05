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
