"""Publish PEREZ AI state to the independent Telegram service.

Failures are deliberately non-fatal: market scanning, paper trading and the
local Telegram updater must never depend on this remote status endpoint.
"""
from __future__ import annotations

import os

import requests

ENDPOINT = os.getenv("PEREZ_REMOTE_STATUS_URL", "").strip()
TOKEN = os.getenv("PEREZ_REMOTE_STATUS_TOKEN", "").strip()
TIMEOUT = max(2, int(os.getenv("PEREZ_REMOTE_STATUS_TIMEOUT", "5")))


def publish(kind: str, data: dict) -> bool:
    if not ENDPOINT:
        return False
    if kind not in {"heartbeat", "forecast", "trade"}:
        return False
    try:
        response = requests.post(
            ENDPOINT,
            json={"kind": kind, "data": data},
            headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Remote status publish failed (non-fatal): {exc}")
        return False
