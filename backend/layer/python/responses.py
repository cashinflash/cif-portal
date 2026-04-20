"""HTTP response helpers for Lambda proxy integration (API Gateway HTTP API)."""

import json
from typing import Any


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # CloudFront strips this; API GW value is harmless
    "Access-Control-Allow-Credentials": "true",
    "Content-Type": "application/json",
}


def ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def error(message: str, status: int = 400, **extra) -> dict:
    payload = {"error": message}
    payload.update(extra)
    return {
        "statusCode": status,
        "headers": _CORS_HEADERS,
        "body": json.dumps(payload),
    }


def parse_body(event: dict) -> dict:
    """Decode JSON body from an HTTP API v2 event. Returns {} on empty."""
    raw = event.get("body") or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def get_claims(event: dict) -> dict:
    """Extract JWT claims from HTTP API v2 Cognito authorizer context."""
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]
    except (KeyError, TypeError):
        return {}
