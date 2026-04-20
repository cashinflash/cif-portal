"""Cognito Pre-Sign-Up trigger — enforces one portal account per Vergent customer.

Cognito's native uniqueness is scoped to the `username` attribute only (email in
our pool). That means a returning customer could sign up again under a different
email address — we need a stronger check. This Lambda runs on every SignUp
attempt, inspects the incoming `custom:vergentCustomerId` (stamped by our
signup.html flow) and the `email`, and aborts the SignUp if either already
belongs to someone in the pool.

Errors raised here surface to the SPA as `UserLambdaValidationException` with
the message we throw inside. signup.html's `humanizeError()` keys off the
codes DUPLICATE_VERGENT_CUSTOMER and DUPLICATE_EMAIL.
"""

import os
import boto3
from botocore.exceptions import ClientError

_cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def lambda_handler(event, context):
    # Cognito passes the pool ID with every invocation — no env var needed,
    # which conveniently avoids a CloudFormation cycle (UserPool → Lambda via
    # LambdaConfig; we don't want Lambda → UserPool via env var).
    pool_id = event.get("userPoolId", "")
    attrs   = event.get("request", {}).get("userAttributes", {}) or {}
    vcid    = (attrs.get("custom:vergentCustomerId") or "").strip()
    email   = (attrs.get("email") or "").strip().lower()
    incoming_sub = event.get("userName", "")

    if email and _exists_by_email(pool_id, email, exclude_sub=incoming_sub):
        raise Exception("DUPLICATE_EMAIL")

    if vcid and _exists_by_vergent_id(pool_id, vcid, exclude_sub=incoming_sub):
        raise Exception("DUPLICATE_VERGENT_CUSTOMER")

    # Default: let Cognito continue. User stays UNCONFIRMED until they enter
    # the verification code.
    return event


def _exists_by_email(pool_id: str, email: str, *, exclude_sub: str = "") -> bool:
    """Fast path — Cognito natively supports filtering on email."""
    if not pool_id:
        return False
    try:
        resp = _cognito.list_users(
            UserPoolId=pool_id,
            Filter=f'email = "{email}"',
            Limit=3,
        )
    except ClientError:
        return False
    for u in resp.get("Users", []):
        if u.get("Username") != exclude_sub:
            return True
    return False


def _exists_by_vergent_id(pool_id: str, vcid: str, *, exclude_sub: str = "") -> bool:
    """Slow path — custom attributes aren't filterable, so paginate the pool
    and match client-side. Fine at O(<1000) users; move to a DynamoDB index
    populated by a Post-Confirmation trigger once we outgrow that.
    """
    if not pool_id:
        return False
    pagination_token = None
    scanned = 0
    MAX_SCAN = 5000
    while scanned < MAX_SCAN:
        kwargs = {"UserPoolId": pool_id, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        try:
            resp = _cognito.list_users(**kwargs)
        except ClientError:
            return False
        for u in resp.get("Users", []):
            if u.get("Username") == exclude_sub:
                continue
            for a in u.get("Attributes", []):
                if a.get("Name") == "custom:vergentCustomerId" and a.get("Value") == vcid:
                    return True
        scanned += len(resp.get("Users", []))
        pagination_token = resp.get("PaginationToken")
        if not pagination_token:
            break
    return False
