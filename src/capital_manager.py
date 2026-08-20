from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def extract_available_capital(response: Any) -> float:
    """Extract usable cash from Angel One RMS data without a hard-coded capital."""
    data = response.get("data", {}) if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError("Angel One RMS response has no usable data")

    # Prefer free cash. Margin/net values are only fallbacks because they can
    # include collateral or other non-cash buying power.
    for key in (
        "availablecash",
        "availableCash",
        "availableintradaypayin",
        "availablelimitmargin",
        "net",
    ):
        value = _to_float(data.get(key))
        if value is not None:
            return round(value, 2)

    raise RuntimeError("Angel One RMS response did not expose available capital")


def get_available_capital(client) -> float:
    """Read the current available Angel One capital before risk/scanning."""
    response = client.get_rms_limit()
    capital = extract_available_capital(response)
    if capital <= 0:
        raise RuntimeError(f"No available trading capital reported: Rs {capital:.2f}")
    return capital
