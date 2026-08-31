"""Cross-source market-data validation for PEREZ AI."""

from __future__ import annotations

import os
from typing import Any

from src import upstox_market_data as upstox


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def configured() -> bool:
    """Return True when the operator explicitly enabled Upstox validation."""
    return _truthy(os.getenv("UPSTOX_ENABLED", "false"))


def _max_price_deviation_pct() -> float:
    try:
        value = float(os.getenv("UPSTOX_MAX_PRICE_DEVIATION_PCT", "0.35"))
    except ValueError:
        value = 0.35
    return max(0.05, min(value, 5.0))


def validate_against_upstox(
    symbol: str,
    primary_close: float,
    snapshot: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Validate an Angel/primary closed candle against Upstox.

    If Upstox validation is enabled, any missing/invalid/stale secondary data
    fails closed.  This is intentionally conservative: disagreement is a
    no-trade condition rather than a signal to choose the more favorable feed.
    """
    if not configured():
        return True, {"enabled": False, "status": "DISABLED"}

    if not upstox.access_token():
        return False, {"enabled": True, "status": "MISSING_ACCESS_TOKEN"}

    if not upstox.instrument_keys().get(str(symbol).upper().strip()):
        return False, {"enabled": True, "status": "MISSING_INSTRUMENT_KEY"}

    if not isinstance(snapshot, dict):
        return False, {"enabled": True, "status": "MISSING_SNAPSHOT"}

    if snapshot.get("error"):
        return False, {
            "enabled": True,
            "status": "ERROR",
            "error": str(snapshot.get("error")),
        }

    try:
        secondary_close = float(snapshot["closed_5m_close"])
        secondary_ltp = float(snapshot["ltp"])
        if primary_close <= 0 or secondary_close <= 0 or secondary_ltp <= 0:
            raise ValueError("non-positive market price")
        deviation_pct = abs(primary_close - secondary_close) / primary_close * 100.0
        max_deviation = _max_price_deviation_pct()
        ok = deviation_pct <= max_deviation
        details = {
            "enabled": True,
            "status": "AGREE" if ok else "DISAGREE",
            "primary_close": round(primary_close, 6),
            "upstox_closed_5m_close": round(secondary_close, 6),
            "upstox_ltp": round(secondary_ltp, 6),
            "deviation_pct": round(deviation_pct, 4),
            "max_deviation_pct": max_deviation,
            "upstox_candle_age_seconds": snapshot.get("candle_age_seconds"),
            "upstox_instrument_key": snapshot.get("instrument_key"),
        }
        return ok, details
    except Exception as exc:
        return False, {"enabled": True, "status": "ERROR", "error": str(exc)}
