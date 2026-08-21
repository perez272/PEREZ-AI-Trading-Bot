"""Best-effort remote heartbeat publisher for the PEREZ AI bot.

The trading process must remain fully functional when no remote status
endpoint is configured or when the endpoint is unavailable.  This module
therefore treats remote publishing as optional and never raises from
``publish`` for transport/configuration errors.
"""

import json
import os
from typing import Any

import requests


def publish(event: str, payload: dict[str, Any]) -> bool:
    """Publish a heartbeat/event when a remote endpoint is configured.

    Configuration is intentionally opt-in via ``PEREZ_REMOTE_STATUS_URL``.
    If it is unset, the local heartbeat remains the source of truth and this
    function simply returns False.
    """
    url = os.getenv("PEREZ_REMOTE_STATUS_URL", "").strip()
    if not url:
        return False

    token = os.getenv("PEREZ_REMOTE_STATUS_TOKEN", "").strip()
    body = {"event": event, "payload": payload}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = float(os.getenv("PEREZ_REMOTE_STATUS_TIMEOUT", "5"))
    try:
        response = requests.post(url, data=json.dumps(body), headers=headers, timeout=timeout)
        response.raise_for_status()
        return True
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"Remote heartbeat publish failed (non-fatal): {exc}")
        return False
