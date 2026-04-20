"""GET /api/me — returns current session info from the Cognito JWT claims."""

from responses import ok, get_claims


def lambda_handler(event, context):
    claims = get_claims(event)
    return ok({
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "emailVerified": claims.get("email_verified") in ("true", True),
        "vergentCustomerId": claims.get("custom:vergentCustomerId"),
        "firstName": claims.get("given_name"),
        "lastName": claims.get("family_name"),
    })
