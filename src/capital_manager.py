from __future__ import annotations

import os
from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def extract_available_capital(response: Any) -> float:
    """Extract usable cash from Angel One RMS data without a hard-coded live capital."""
    data = response.get("data", {}) if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError("Angel One RMS response has no usable data")

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


def get_paper_capital() -> float:
    """Return explicitly configured virtual capital for paper trading."""
    raw = os.getenv("PAPER_CAPITAL", "50000")
    try:
        capital = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PAPER_CAPITAL must be a positive number") from exc
    if capital <= 0:
        raise RuntimeError("PAPER_CAPITAL must be greater than Rs 0")
    return round(capital, 2)


def get_available_capital(client, paper_mode: bool = False) -> float:
    """Get capital from virtual paper balance or Angel One RMS in live mode."""
    if paper_mode:
        return get_paper_capital()

    response = client.get_rms_limit()
    capital = extract_available_capital(response)
    if capital <= 0:
        raise RuntimeError(f"No available trading capital reported: Rs {capital:.2f}")
    return capital
