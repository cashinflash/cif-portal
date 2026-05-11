"""Impersonation tokens for cif-dashboard admins.

Operators in the cif-admin Cognito group use cif-dashboard's
Customers tab to find a portal-registered customer, then click
"View as customer" — that posts to POST /api/admin/impersonate
which mints a single-purpose token here. The token is delivered
back as a URL like:

    https://apply.cashinflash.com/?impersonationToken=<token>

The portal frontend strips the param off the URL, stashes the
token in sessionStorage, and sends it as X-Impersonation-Token
on every API call. Customer Lambdas honor the header by
overriding the request's claims with the target customer's
identity (loaded from the DDB row this module wrote) — but
only for read-only HTTP methods.

Security properties:
  - 15-minute TTL on every token (DDB native TTL on expiresAt).
  - Token row records the admin email (caller's JWT claim) and
    the target customer for audit. Survives until DDB TTL
    cleanup (~48h after expiry).
  - Manual end via POST /api/admin/end-impersonate sets endedAt
    so subsequent lookups treat the token as dead even before
    its TTL fires.
  - Write methods are blocked at the customer-Lambda layer
    (see handlers/loans.py middleware). This module just
    issues + validates tokens — it doesn't enforce the
    read-only contract directly.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

import boto3

log = logging.getLogger()

_dynamo = boto3.client(
    "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"),
)

IMPERSONATIONS_TABLE = os.environ.get(
    "IMPERSONATIONS_TABLE", "cif-portal-impersonations-dev"
)

PORTAL_ORIGIN = os.environ.get(
    "PORTAL_ORIGIN", "https://d1zucrj1ouu3c.cloudfront.net"
)

TOKEN_TTL_SECONDS = 15 * 60  # 15 minutes


def _json(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _claims(event: Dict[str, Any]) -> Dict[str, Any]:
    return (((event.get("requestContext") or {}).get("authorizer") or {})
            .get("jwt", {}).get("claims") or {})


def mint_token(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/admin/impersonate

    Body: {"cognitoSub": "<sub>"} (preferred — unique)
       OR {"customerId": "<vergent_cid>"} (looked up in Cognito)

    Returns {token, portalUrl, expiresAt, target: {...}}
    """
    # Auth: only cif-admin Cognito group. Imported lazily to avoid
    # cross-module init order with plaid.py at handler load.
    from handlers import plaid
    claims = _claims(event)
    err = plaid._require_admin_group(claims)
    if err:
        return err

    admin_user = (claims.get("email") or claims.get("cognito:username")
                  or claims.get("sub") or "unknown")

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _json(400, {"error": "invalid_json"})
    if not isinstance(body, dict):
        return _json(400, {"error": "invalid_body"})

    target_sub = (body.get("cognitoSub") or "").strip()
    target_cid = (body.get("customerId") or "").strip()

    # Resolve target → need cognitoSub, customerId, email, name.
    from handlers import auth_mfa
    target_user: Optional[Dict[str, Any]] = None
    if target_sub:
        try:
            resp = auth_mfa.cognito.admin_get_user(
                UserPoolId=auth_mfa.USER_POOL_ID, Username=target_sub,
            )
            attrs = {a["Name"]: a["Value"]
                     for a in resp.get("UserAttributes", [])}
            target_user = {
                "Username": resp.get("Username"),
                "Attrs": attrs,
                "Status": resp.get("UserStatus"),
            }
        except Exception as exc:
            log.warning("impersonate: admin_get_user failed sub=%s: %s",
                        target_sub, exc)
    elif target_cid:
        target_user = auth_mfa._find_cognito_user_by_vergent_id(target_cid)
    else:
        return _json(400, {"error": "missing_target"})

    if not target_user:
        return _json(404, {"error": "target_not_found"})

    attrs = target_user.get("Attrs") or {}
    final_sub = attrs.get("sub") or target_user.get("Username")
    final_cid = attrs.get("custom:vergentCustomerId") or target_cid or ""
    target_email = attrs.get("email") or ""
    target_first = attrs.get("given_name") or ""
    target_last = attrs.get("family_name") or ""

    if not final_cid:
        # Customer hasn't been linked to a Vergent record yet — no
        # point letting the operator impersonate them, since the
        # portal would 404 looking up loans/profile/etc.
        return _json(400, {"error": "target_missing_vergent_link"})

    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + TOKEN_TTL_SECONDS

    try:
        _dynamo.put_item(
            TableName=IMPERSONATIONS_TABLE,
            Item={
                "token":             {"S": token},
                "adminUser":         {"S": str(admin_user)},
                "targetCognitoSub":  {"S": str(final_sub)},
                "targetCustomerId":  {"S": str(final_cid)},
                "targetEmail":       {"S": str(target_email)},
                "targetFirstName":   {"S": str(target_first)},
                "targetLastName":    {"S": str(target_last)},
                "createdAt":         {"N": str(now)},
                "expiresAt":         {"N": str(expires_at)},
            },
        )
    except Exception as exc:
        log.exception("impersonate: ddb put failed: %s", exc)
        return _json(502, {"error": "ddb_write_failed",
                           "detail": f"{type(exc).__name__}: {exc}"})

    portal_url = (
        f"{PORTAL_ORIGIN.rstrip('/')}/dashboard.html"
        f"#impersonationToken={token}"
    )
    # Note: cif-dashboard's /api/portal-customers/impersonate proxy
    # rebuilds this URL with additional fragment params (operator's
    # service JWT, target name, customerId, expiry epoch). The value
    # we return here is only useful for direct testing of the mint
    # endpoint — the production flow goes through that proxy.
    log.info("impersonate: minted admin=%s target_sub=%s cid=%s expires=%d",
             admin_user, final_sub, final_cid, expires_at)
    return _json(200, {
        "token": token,
        "portalUrl": portal_url,
        "expiresAt": expires_at,
        "target": {
            "cognitoSub": final_sub,
            "customerId": final_cid,
            "email": target_email,
            "firstName": target_first,
            "lastName": target_last,
            "fullName": (" ".join(p for p in (target_first, target_last) if p)).strip(),
        },
    })


def lookup_token(token: str) -> Optional[Dict[str, Any]]:
    """Resolve a token to its target row, or None if missing /
    expired / ended. Called from customer Lambdas' middleware
    (handlers.loans._claims_with_impersonation, etc.)."""
    if not token:
        return None
    try:
        resp = _dynamo.get_item(
            TableName=IMPERSONATIONS_TABLE,
            Key={"token": {"S": token}},
        )
    except Exception as exc:
        log.warning("impersonate lookup ddb failed: %s", exc)
        return None
    item = resp.get("Item") or {}
    if not item:
        return None
    now = int(time.time())
    expires_at = int(item.get("expiresAt", {}).get("N", "0") or 0)
    if expires_at and expires_at < now:
        return None
    if "endedAt" in item:
        return None
    return {
        "token": token,
        "adminUser": item.get("adminUser", {}).get("S"),
        "targetCognitoSub": item.get("targetCognitoSub", {}).get("S"),
        "targetCustomerId": item.get("targetCustomerId", {}).get("S"),
        "targetEmail": item.get("targetEmail", {}).get("S"),
        "targetFirstName": item.get("targetFirstName", {}).get("S"),
        "targetLastName": item.get("targetLastName", {}).get("S"),
        "expiresAt": expires_at,
    }


def claims_with_impersonation(event: Dict[str, Any]) -> Dict[str, Any]:
    """Drop-in replacement for the per-Lambda _claims() helper.

    Returns the JWT claims for the request — but if the request
    carries a valid X-Impersonation-Token header, returns
    synthesized claims for the target customer instead. The
    returned dict includes a `_impersonation` key when synthesized
    so the caller can detect this state for the write-block check
    below.

    Result is cached on the event dict so repeated calls within
    the same Lambda invocation skip the DDB lookup."""
    cached = event.get("_impersonation_resolved_claims")
    if cached is not None:
        return cached

    headers = {(k or "").lower(): v
               for k, v in (event.get("headers") or {}).items()}
    token = headers.get("x-impersonation-token") or ""
    info = lookup_token(token) if token else None

    if info:
        claims: Dict[str, Any] = {
            "sub": info["targetCognitoSub"] or "",
            "email": info["targetEmail"] or "",
            "custom:vergentCustomerId": info["targetCustomerId"] or "",
            "given_name": info.get("targetFirstName") or "",
            "family_name": info.get("targetLastName") or "",
            "_impersonation": info,
        }
    else:
        rc = event.get("requestContext") or {}
        auth = rc.get("authorizer") or {}
        jwt = auth.get("jwt") or {}
        claims = dict(jwt.get("claims") or {})

    event["_impersonation_resolved_claims"] = claims
    return claims


def maybe_block_write(event: Dict[str, Any],
                       claims: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a 403 response dict if the request is impersonated
    AND the HTTP method is a write (POST/PUT/PATCH/DELETE),
    otherwise None.

    The "End impersonation" endpoint is exempt — the in-portal
    banner must be able to revoke its own token. Admin endpoints
    (the cif-admin operator session) shouldn't ever carry an
    impersonation token, so they fall through this check
    untouched."""
    if not claims.get("_impersonation"):
        return None
    http = (event.get("requestContext") or {}).get("http") or {}
    method = (http.get("method") or "").upper()
    path = http.get("path") or ""
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if path.endswith("/admin/end-impersonate"):
        return None
    return {
        "statusCode": 403,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "error": "impersonation_read_only",
            "message": "This action is disabled while viewing as customer.",
        }),
    }


def end_token(event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/admin/end-impersonate — operator-triggered token
    revocation. Marks the row endedAt so subsequent lookups
    return None even before TTL fires. Auth: cif-admin group OR
    the impersonation token itself (the in-portal banner's
    "End now" button calls this from the impersonated session)."""
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _json(400, {"error": "invalid_json"})

    headers = {k.lower(): v for k, v in
               (event.get("headers") or {}).items()}
    token = (body.get("token") if isinstance(body, dict) else None) \
        or headers.get("x-impersonation-token") or ""
    if not token:
        return _json(400, {"error": "missing_token"})

    # Either the original admin (via JWT) or the current
    # impersonation session can end. We don't enforce a strict
    # match here — operators or the impersonated user pressing
    # End should both succeed.
    try:
        _dynamo.update_item(
            TableName=IMPERSONATIONS_TABLE,
            Key={"token": {"S": token}},
            UpdateExpression="SET endedAt = :n",
            ExpressionAttributeValues={
                ":n": {"N": str(int(time.time()))},
            },
        )
    except Exception as exc:
        log.warning("impersonate end ddb failed: %s", exc)
        return _json(502, {"error": "ddb_write_failed"})
    return _json(200, {"ok": True})
