"""Persistent Telegram status updater for PEREZ AI.

This process is intentionally independent from the trading loop. A scanner
failure therefore cannot silently kill Telegram status delivery, and a
Telegram outage cannot kill the scanner. Alerts are deduplicated and rate
limited.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.telegram_alert import send_alert

HEARTBEAT_PATH = Path(os.getenv("PEREZ_HEARTBEAT_PATH", "data/runtime/heartbeat.json"))
POLL_SECONDS = max(15, int(os.getenv("TELEGRAM_UPDATER_POLL_SECONDS", "30")))
ALERT_COOLDOWN_SECONDS = max(60, int(os.getenv("TELEGRAM_STATUS_COOLDOWN_SECONDS", "300")))


def _read_heartbeat() -> dict:
    try:
        return json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown", "reason": "HEARTBEAT_UNAVAILABLE"}


def run_forever() -> None:
    last_fingerprint = ""
    last_sent = 0.0
    while True:
        heartbeat = _read_heartbeat()
        fingerprint = json.dumps(
            {k: heartbeat.get(k) for k in ("status", "reason", "symbol", "error")},
            sort_keys=True,
        )
        now = time.time()
        if fingerprint != last_fingerprint and now - last_sent >= ALERT_COOLDOWN_SECONDS:
            message = (
                "PEREZ AI LIVE STATUS\n\n"
                f"Status: {heartbeat.get('status', 'unknown')}\n"
                f"Reason: {heartbeat.get('reason', '')}\n"
                f"Symbol: {heartbeat.get('symbol', '')}\n"
                f"Updated: {heartbeat.get('timestamp_utc', '')}"
            )
            if send_alert(message):
                last_fingerprint = fingerprint
                last_sent = now
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
