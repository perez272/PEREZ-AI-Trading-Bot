"""Time-based paper-trade exit state machine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)
MAX_HOLD_MINUTES = 15.0
NO_ACTION = "NO_ACTION"
TRAIL_TO_BREAKEVEN = "TRAIL_TO_BREAKEVEN"
TIME_STOP_EXIT = "TIME_STOP_EXIT"


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip().replace("Z", "+00:00")
        if not raw:
            raise ValueError("timestamp is required")
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def evaluate_time_stop(
    entry_time: Any,
    current_time: Any,
    target1: float,
    current_price: float,
    entry_price: float,
    max_hold_minutes: float = MAX_HOLD_MINUTES,
    target1_reached: bool = False,
    logger: logging.Logger | None = None,
) -> str:
    """Return the time-stop action without mutating trade state."""
    if target1_reached:
        return NO_ACTION
    if float(max_hold_minutes) < 0:
        raise ValueError("max_hold_minutes must be non-negative")
    target1 = float(target1)
    current_price = float(current_price)
    entry_price = float(entry_price)
    hold_minutes = (_as_datetime(current_time) - _as_datetime(entry_time)).total_seconds() / 60.0
    if hold_minutes < 0:
        raise ValueError("current_time cannot precede entry_time")

    if hold_minutes < float(max_hold_minutes):
        return NO_ACTION

    if current_price > entry_price:
        action = TRAIL_TO_BREAKEVEN
    else:
        action = TIME_STOP_EXIT

    (logger or LOGGER).warning(
        "%s hold_duration_minutes=%.2f entry=%.4f current=%.4f target1=%.4f",
        action,
        hold_minutes,
        entry_price,
        current_price,
        target1,
    )
    return action
