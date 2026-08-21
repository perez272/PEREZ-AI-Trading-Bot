"""Global Angel One API rate limiting and retry helpers."""
from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Callable, TypeVar, Any

F = TypeVar("F", bound=Callable[..., Any])

_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
_MIN_INTERVAL = 2.0
_MAX_RETRIES = 4


def wait_for_request(min_interval: float = _MIN_INTERVAL) -> None:
    """Serialize API calls and enforce a minimum gap between requests."""
    global _LAST_REQUEST
    with _LOCK:
        now = time.monotonic()
        delay = min_interval - (now - _LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
        _LAST_REQUEST = time.monotonic()


def is_rate_limited(result: Any) -> bool:
    if isinstance(result, dict):
        message = str(result.get("message", "")).lower()
        code = str(result.get("errorcode", "")).upper()
        return code == "AB1021" or "too many requests" in message
    return False


def call_with_backoff(func: F, *args: Any, **kwargs: Any) -> Any:
    """Call an Angel One API function with throttling and exponential backoff."""
    delay = 4.0
    last_result = None
    for attempt in range(_MAX_RETRIES + 1):
        wait_for_request()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            if attempt >= _MAX_RETRIES:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
            continue
        last_result = result
        if not is_rate_limited(result):
            return result
        if attempt < _MAX_RETRIES:
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return last_result
