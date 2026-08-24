"""Fail-closed validation primitives for multi-source market data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _bucket(timestamp: datetime, interval_seconds: int) -> datetime:
    epoch = int(timestamp.timestamp())
    return datetime.fromtimestamp(epoch - epoch % interval_seconds, tz=timezone.utc)


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

    if len(required_sources) >= 2 and len(usable) < 2:
        return IntegrityResult(False, "INSUFFICIENT_CORROBORATION", sources=tuple(src for src, _ in usable))

    return IntegrityResult(True, "FRESH_AGREED_DATA", price=sum(prices) / len(prices), sources=tuple(src for src, _ in usable))


def validate_candle_sources(
    sources: Mapping[str, Mapping[str, Any] | None],
    *,
    now: datetime | None = None,
    interval_seconds: int = 300,
    max_age_seconds: float = 600.0,
    max_disagreement_pct: float = 0.50,
    required_sources: tuple[str, ...] = (),
) -> IntegrityResult:
    """Validate that required sources agree on the same latest closed candle."""
    if interval_seconds <= 0 or max_age_seconds < 0:
        return IntegrityResult(False, "INVALID_INTEGRITY_CONFIGURATION")

    now = now or datetime.now(timezone.utc)
    closed_bucket = _bucket(now, interval_seconds) - timedelta(seconds=interval_seconds)
    usable: list[tuple[str, float, datetime]] = []

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
        if age < 0 or age > max_age_seconds:
            continue
        if _bucket(ts, interval_seconds) != closed_bucket:
            continue
        usable.append((name, price, ts))

    missing = [name for name in required_sources if not any(src == name for src, _, _ in usable)]
    if missing:
        return IntegrityResult(False, "REQUIRED_SOURCE_MISSING_OR_STALE", sources=tuple(src for src, _, _ in usable))
    if not usable:
        return IntegrityResult(False, "NO_FRESH_VALID_SOURCE")
    if len(required_sources) >= 2 and len(usable) < 2:
        return IntegrityResult(False, "INSUFFICIENT_CORROBORATION", sources=tuple(src for src, _, _ in usable))

    prices = [price for _, price, _ in usable]
    if len(prices) > 1:
        midpoint = sum(prices) / len(prices)
        spread_pct = (max(prices) - min(prices)) / midpoint * 100
        if spread_pct > max_disagreement_pct:
            return IntegrityResult(False, "SOURCE_DISAGREEMENT", sources=tuple(src for src, _, _ in usable))

    return IntegrityResult(
        True,
        "FRESH_AGREED_CLOSED_CANDLE",
        price=sum(prices) / len(prices),
        sources=tuple(src for src, _, _ in usable),
    )
