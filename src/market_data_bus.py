"""Small in-process bus for validated live market ticks."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.RLock()
_latest: dict[str, dict[str, Any]] = {}
_last_tick_at = 0.0


def publish_tick(message: Any) -> None:
    global _last_tick_at
    if not isinstance(message, dict):
        return
    token = str(message.get("token") or "").strip()
    if not token:
        return
    item = dict(message)
    item["received_at"] = time.time()
    with _lock:
        _latest[token] = item
        _last_tick_at = item["received_at"]


def get_tick(token: str, max_age_seconds: float | None = None) -> dict[str, Any] | None:
    with _lock:
        item = _latest.get(str(token).strip())
        if item is None:
            return None
        result = dict(item)
    if max_age_seconds is not None:
        try:
            if time.time() - float(result.get("received_at", 0)) > float(max_age_seconds):
                return None
        except (TypeError, ValueError):
            return None
    return result


def get_latest() -> dict[str, dict[str, Any]]:
    with _lock:
        return {key: dict(value) for key, value in _latest.items()}


def status() -> dict[str, Any]:
    with _lock:
        return {"tick_count": len(_latest), "last_tick_at": _last_tick_at}
