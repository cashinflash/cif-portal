"""GET /api/health — unauthenticated heartbeat."""

import os
import time

from responses import ok


def lambda_handler(event, context):
    return ok({
        "status": "ok",
        "stage": os.environ.get("STAGE", "dev"),
        "timestamp": int(time.time()),
    })
