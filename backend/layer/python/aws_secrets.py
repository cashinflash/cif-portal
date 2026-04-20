"""Cached Secrets Manager loader.

Lambda containers reuse memory between invocations, so we cache decoded
secrets in-process. First call hits Secrets Manager; subsequent calls are
local dict lookups.
"""

import json
import os
import boto3
from botocore.exceptions import ClientError

_client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_cache: dict[str, dict] = {}


def load(secret_name: str) -> dict:
    """Returns the secret as a dict. Raises on failure.

    Expects the secret value to be JSON like
        {"username": "...", "password": "..."}
    """
    if secret_name in _cache:
        return _cache[secret_name]
    try:
        resp = _client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to load secret {secret_name}: {e}") from e
    raw = resp.get("SecretString") or ""
    parsed = json.loads(raw) if raw else {}
    _cache[secret_name] = parsed
    return parsed


def clear_cache() -> None:
    """Testing helper."""
    _cache.clear()
