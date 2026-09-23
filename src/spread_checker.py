"""Strict Level-2 spread checks for option-entry protection."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)
MAX_SPREAD_PCT = 0.5


def _price(level: Any) -> float:
    if isinstance(level, dict):
        try:
            return float(level.get("price", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def is_spread_safe(
    quote: dict[str, Any] | None,
    max_spread_pct: float = MAX_SPREAD_PCT,
    logger: logging.Logger | None = None,
) -> bool:
    """Return True only when the best bid/ask book is present and within limit."""
    log = logger or LOGGER
    try:
        limit = float(max_spread_pct)
    except (TypeError, ValueError):
        limit = MAX_SPREAD_PCT
    if limit < 0:
        raise ValueError("max_spread_pct must be non-negative")

    depth = quote.get("depth") if isinstance(quote, dict) else None
    buys = depth.get("buy") if isinstance(depth, dict) else None
    sells = depth.get("sell") if isinstance(depth, dict) else None
    bid = _price(buys[0]) if isinstance(buys, list) and buys else 0.0
    ask = _price(sells[0]) if isinstance(sells, list) and sells else 0.0

    if bid <= 0 or ask <= 0 or ask < bid:
        log.warning(
            "TRADE_BLOCKED_SPREAD bid=%.4f ask=%.4f reason=EMPTY_OR_INVALID_BOOK",
            bid,
            ask,
        )
        return False

    spread_pct = (ask - bid) / bid * 100.0
    if spread_pct > limit:
        log.warning(
            "TRADE_BLOCKED_SPREAD bid=%.4f ask=%.4f spread_pct=%.4f max_spread_pct=%.4f",
            bid,
            ask,
            spread_pct,
            limit,
        )
        return False
    return True


def check_upstox_spread(
    client: Any,
    instrument_key: str,
    max_spread_pct: float = MAX_SPREAD_PCT,
    logger: logging.Logger | None = None,
) -> bool:
    """Fetch a full Upstox quote through the existing market-data adapter."""
    if not instrument_key or "|" not in str(instrument_key):
        (logger or LOGGER).warning(
            "TRADE_BLOCKED_SPREAD instrument_key=%s reason=INVALID_INSTRUMENT_KEY",
            instrument_key,
        )
        return False
    try:
        getter = getattr(client, "get_full_market_quote", None) or getattr(client, "get_full_quote", None)
        if getter is None:
            raise AttributeError("Upstox client has no full market quote method")
        quote = getter(str(instrument_key))
    except Exception as exc:
        (logger or LOGGER).warning(
            "TRADE_BLOCKED_SPREAD instrument_key=%s reason=QUOTE_ERROR error=%s",
            instrument_key,
            exc,
        )
        return False
    return is_spread_safe(quote, max_spread_pct=max_spread_pct, logger=logger)
