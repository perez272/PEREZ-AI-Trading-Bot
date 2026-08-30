"""Low-latency Tier-1 option explosive-move detector.

Observational/paper-only signal layer. It detects acceleration BEFORE a large
5-150% option move is complete; it never places orders and never overrides risk gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


def _timestamp(row: dict[str, Any]) -> float | None:
    raw = row.get("observed_ts") or row.get("timestamp") or row.get("ts_utc")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _price_at_or_before(history: list[dict[str, Any]], target_ts: float, fallback: float) -> float:
    best = None
    best_ts = float("-inf")
    for row in history:
        ts = _timestamp(row)
        if ts is None or ts > target_ts or ts < best_ts:
            continue
        value = _value((row.get("market_data") or row), "ltp")
        if value > 0:
            best = value
            best_ts = ts
    return best if best is not None else fallback


def detect_explosive_move(symbol: str, option_type: str, current: dict[str, Any], history: list[dict[str, Any]]) -> ExplosiveMoveSignal | None:
    """Detect early acceleration using actual observation timestamps.

    This is intentionally time-aware: with a 5-second feed, three history
    points are only 15 seconds apart and must NOT be mislabeled as 1/3/5-minute
    observations. A window is used only when an observation at/near that age
    actually exists.
    """
    md = current.get("market_data") or current
    ltp = _value(md, "ltp")
    instrument_key = str(current.get("instrument_key") or md.get("instrument_key") or "")
    if ltp <= 0 or not instrument_key or len(history) < 2:
        return None

    now_ts = _timestamp(current)
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    current_price = ltp
    previous = history[-1]
    previous_price = _value((previous.get("market_data") or previous), "ltp")
    previous_ts = _timestamp(previous)
    elapsed = max(0.0, now_ts - previous_ts) if previous_ts is not None else 5.0

    p1 = _price_at_or_before(history, now_ts - 60.0, 0.0)
    p3 = _price_at_or_before(history, now_ts - 180.0, 0.0)
    p5 = _price_at_or_before(history, now_ts - 300.0, 0.0)

    move_1m = _pct(current_price, p1) if p1 > 0 else 0.0
    move_3m = _pct(current_price, p3) if p3 > 0 else 0.0
    move_5m = _pct(current_price, p5) if p5 > 0 else 0.0

    velocity = _pct(current_price, previous_price) * (60.0 / max(elapsed, 1.0)) if previous_price > 0 else 0.0
    older = history[-2] if len(history) >= 2 else None
    older_price = _value((older.get("market_data") or older), "ltp") if older else 0.0
    older_ts = _timestamp(older) if older else None
    older_elapsed = max(0.0, (previous_ts - older_ts)) if previous_ts is not None and older_ts is not None else elapsed
    previous_velocity = _pct(previous_price, older_price) * (60.0 / max(older_elapsed, 1.0)) if older_price > 0 else 0.0
    acceleration = velocity - previous_velocity

    volumes = [_value((x.get("market_data") or x), "volume") for x in history]
    current_volume = _value(md, "volume")
    valid_volumes = [v for v in volumes if v > 0]
    avg_volume = sum(valid_volumes) / len(valid_volumes) if valid_volumes else 0.0
    volume_ratio = current_volume / avg_volume if avg_volume > 0 and current_volume > 0 else 0.0

    bid = _value(md, "bid_price", _value(md, "bid"))
    ask = _value(md, "ask_price", _value(md, "ask"))
    spread_pct = ((ask - bid) / ltp * 100.0) if ltp > 0 and ask >= bid > 0 else 999.0

    reasons: list[str] = []
    score = 0.0
    if move_1m >= 1.5:
        score += 20; reasons.append("1m_price_acceleration")
    if move_3m >= 2.5:
        score += 20; reasons.append("3m_momentum")
    if move_5m >= 4.0:
        score += 15; reasons.append("5m_expansion")
    if acceleration >= 0.75:
        score += 20; reasons.append("accelerating_velocity")
    if volume_ratio >= 1.5:
        score += 15; reasons.append("volume_expansion")
    elif volume_ratio >= 1.2:
        score += 8; reasons.append("volume_support")
    if spread_pct <= 2.0:
        score += 10; reasons.append("liquid_spread")
    elif spread_pct > 5.0:
        score -= 20; reasons.append("wide_spread_penalty")

    # Early means the move is accelerating but has not already become a
    # completed large move. This is a precursor signal, never a guarantee.
    early = score >= 55 and acceleration >= 0.5 and (move_5m == 0.0 or move_5m < 20.0)
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
