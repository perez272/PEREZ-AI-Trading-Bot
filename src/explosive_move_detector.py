"""Low-latency Tier-1 option explosive-move detector.

Observational/paper-only signal layer. It detects acceleration BEFORE a large
5-100% option move is complete; it never places orders and never overrides risk gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExplosiveMoveSignal:
    symbol: str
    option_type: str
    instrument_key: str
    ltp: float
    move_1m_pct: float
    move_3m_pct: float
    move_5m_pct: float
    velocity_pct_per_min: float
    acceleration_pct_per_min2: float
    volume_ratio: float
    spread_pct: float
    score: float
    early: bool
    reasons: tuple[str, ...]


def _pct(now: float, old: float) -> float:
    return ((now - old) / old * 100.0) if old > 0 else 0.0


def _value(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def detect_explosive_move(
    symbol: str,
    option_type: str,
    current: dict[str, Any],
    history: list[dict[str, Any]],
) -> ExplosiveMoveSignal | None:
    """Detect early acceleration using real timestamp-based windows."""
    from datetime import datetime, timezone

    md = current.get("market_data") or current
    ltp = _value(md, "ltp")
    instrument_key = str(
        current.get("instrument_key")
        or md.get("instrument_key")
        or ""
    )

    if ltp <= 0 or not instrument_key:
        return None

    def _ts(row):
        raw = row.get("observed_ts")
        if not raw:
            return None
        try:
            ts = datetime.fromisoformat(str(raw))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    current_ts = _ts(current)
    if current_ts is None:
        return None

    points = []
    for row in history:
        ts = _ts(row)
        price = _value((row.get("market_data") or row), "ltp")
        if ts and price > 0 and ts < current_ts:
            points.append((ts, price))

    if not points:
        return None

    points.sort(key=lambda x: x[0])

    def _price_at_or_before(minutes):
        target = minutes * 60.0
        candidates = []

        for ts, price in points:
            age = (current_ts - ts).total_seconds()
            if age >= target:
                candidates.append((abs(age - target), ts, price))

        if not candidates:
            return None

        _, ts, price = min(candidates, key=lambda x: x[0])
        elapsed = (current_ts - ts).total_seconds() / 60.0
        return ts, price, elapsed

    w1 = _price_at_or_before(1)
    w3 = _price_at_or_before(3)
    w5 = _price_at_or_before(5)

    # Never fabricate a 3m/5m measurement from a shorter history.
    if not w1 or not w3 or not w5:
        return None

    ts1, p1, elapsed1 = w1
    _, p3, _ = w3
    _, p5, _ = w5

    move_1m = _pct(ltp, p1)
    move_3m = _pct(ltp, p3)
    move_5m = _pct(ltp, p5)

    velocity = move_1m / elapsed1 if elapsed1 > 0 else 0.0

    previous_velocity = 0.0
    prior = [(ts, price) for ts, price in points if ts < ts1]

    if prior:
        prev_ts, prev_price = prior[-1]
        elapsed_prev = (ts1 - prev_ts).total_seconds() / 60.0

        if elapsed_prev > 0 and prev_price > 0:
            previous_move = _pct(p1, prev_price)
            previous_velocity = previous_move / elapsed_prev

    acceleration = velocity - previous_velocity

    volumes = [
        _value((x.get("market_data") or x), "volume")
        for x in history
    ]
    current_volume = _value(md, "volume")
    valid_volumes = [v for v in volumes if v > 0]

    avg_volume = (
        sum(valid_volumes) / len(valid_volumes)
        if valid_volumes else 0.0
    )

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0 and current_volume > 0
        else 0.0
    )

    bid = _value(md, "bid_price", _value(md, "bid"))
    ask = _value(md, "ask_price", _value(md, "ask"))

    spread_pct = (
        (ask - bid) / ltp * 100.0
        if ltp > 0 and ask >= bid > 0
        else 999.0
    )

    reasons = []
    score = 0.0

    if move_1m >= 1.5:
        score += 20
        reasons.append("1m_price_acceleration")

    if move_3m >= 2.5:
        score += 20
        reasons.append("3m_momentum")

    if move_5m >= 4.0:
        score += 15
        reasons.append("5m_expansion")

    if acceleration >= 0.75:
        score += 20
        reasons.append("accelerating_velocity")

    if volume_ratio >= 1.5:
        score += 15
        reasons.append("volume_expansion")
    elif volume_ratio >= 1.2:
        score += 8
        reasons.append("volume_support")

    if spread_pct <= 2.0:
        score += 10
        reasons.append("liquid_spread")
    elif spread_pct > 5.0:
        score -= 20
        reasons.append("wide_spread_penalty")

    early = (
        score >= 55
        and acceleration >= 0.5
        and move_5m < 20.0
    )

    return ExplosiveMoveSignal(
        symbol=symbol,
        option_type=option_type,
        instrument_key=instrument_key,
        ltp=ltp,
        move_1m_pct=round(move_1m, 4),
        move_3m_pct=round(move_3m, 4),
        move_5m_pct=round(move_5m, 4),
        velocity_pct_per_min=round(velocity, 4),
        acceleration_pct_per_min2=round(acceleration, 4),
        volume_ratio=round(volume_ratio, 4),
        spread_pct=round(spread_pct, 4),
        score=round(max(0.0, min(100.0, score)), 2),
        early=early,
        reasons=tuple(reasons),
    )
