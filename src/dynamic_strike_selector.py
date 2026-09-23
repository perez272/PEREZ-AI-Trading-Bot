"""Deterministic ATM/ITM strike selection for index options."""

from __future__ import annotations

import math

STRIKE_STEPS = {
    "NIFTY": 50.0,
    "BANKNIFTY": 100.0,
    "FINNIFTY": 50.0,
    "MIDCPNIFTY": 25.0,
    "NIFTYNXT50": 50.0,
}


def select_target_strike(
    symbol: str,
    spot: float,
    option_type: str,
    itm_depth: int = 1,
) -> float:
    """Return ATM or ITM strike using the configured index strike step."""
    symbol = str(symbol or "").strip().upper()
    option_type = str(option_type or "").strip().upper()
    if symbol not in STRIKE_STEPS:
        raise ValueError(f"Unsupported index symbol: {symbol}")
    if option_type not in {"CE", "PE"}:
        raise ValueError(f"Unsupported option type: {option_type}")
    if int(itm_depth) != itm_depth or itm_depth < 0:
        raise ValueError("itm_depth must be a non-negative integer")
    spot = float(spot)
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("spot must be a positive finite number")

    step = STRIKE_STEPS[symbol]
    # Avoid Python's banker's rounding at exact half-step boundaries.
    atm = math.floor((spot / step) + 0.5) * step
    offset = int(itm_depth) * step
    target = atm - offset if option_type == "CE" else atm + offset
    return float(target)
