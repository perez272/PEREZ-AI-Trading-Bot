"""Fail-closed validation primitives for multi-source market data.

This module is intentionally not wired into execution yet. It defines the
contract that production routing must satisfy before a quote/candle can be
trusted by the trading engine.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True)
class IntegrityResult:
    ok: bool
    reason: str
    price: float | None = None
    sources: tuple[str, ...] = ()


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_sources(
    sources: Mapping[str, Mapping[str, Any] | None],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
    max_disagreement_pct: float = 0.25,
    required_sources: tuple[str, ...] = (),
) -> IntegrityResult:
    """Validate quotes and fail closed on missing/stale/disagreeing data."""
    now = now or datetime.now(timezone.utc)
    usable: list[tuple[str, float]] = []
    for name, payload in sources.items():
        if not payload or "price" not in payload or "timestamp" not in payload:
            continue
        try:
            price = float(payload["price"])
        except (TypeError, ValueError):
            continue
        if not isfinite(price) or price <= 0:
            continue
        ts = _timestamp(payload["timestamp"])
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if age < -5 or age > max_age_seconds:
            continue
        usable.append((name, price))

    missing = [name for name in required_sources if not any(src == name for src, _ in usable)]
    if missing:
        return IntegrityResult(False, "REQUIRED_SOURCE_MISSING_OR_STALE", sources=tuple(src for src, _ in usable))
    if not usable:
        return IntegrityResult(False, "NO_FRESH_VALID_SOURCE")

    prices = [price for _, price in usable]
    if len(prices) > 1:
        midpoint = sum(prices) / len(prices)
        spread_pct = (max(prices) - min(prices)) / midpoint * 100
        if spread_pct > max_disagreement_pct:
            return IntegrityResult(False, "SOURCE_DISAGREEMENT", sources=tuple(src for src, _ in usable))

    # Never silently select a lone source when callers requested corroboration.
    if len(required_sources) >= 2 and len(usable) < 2:
        return IntegrityResult(False, "INSUFFICIENT_CORROBORATION", sources=tuple(src for src, _ in usable))

    return IntegrityResult(True, "FRESH_AGREED_DATA", price=sum(prices) / len(prices), sources=tuple(src for src, _ in usable))
