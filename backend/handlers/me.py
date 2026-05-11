"""GET /api/me — returns current session info from the Cognito JWT claims.

Honors X-Impersonation-Token by returning the target customer's
identity (via handlers.impersonation.claims_with_impersonation),
so an impersonated portal session sees the impersonated user as
"me" instead of the operator's admin account. Also surfaces an
"impersonation" object so the portal frontend can render the
"viewing as customer" banner without an extra round-trip."""

from responses import ok
from handlers import impersonation


def lambda_handler(event, context):
    claims = impersonation.claims_with_impersonation(event)
    info = claims.get("_impersonation") or None
    body = {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "emailVerified": claims.get("email_verified") in ("true", True),
        "vergentCustomerId": claims.get("custom:vergentCustomerId"),
        "firstName": claims.get("given_name"),
        "lastName": claims.get("family_name"),
    }
    if info:
        body["impersonation"] = {
            "active": True,
            "adminUser": info.get("adminUser"),
            "expiresAt": info.get("expiresAt"),
            "readOnly": True,
        }
    return ok(body)
