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


def detect_explosive_move(symbol: str, option_type: str, current: dict[str, Any], history: list[dict[str, Any]]) -> ExplosiveMoveSignal | None:
    """Detect early acceleration from recent option observations.

    history is oldest -> newest and should contain observations no older than 5 minutes.
    Thresholds are deliberately precursor thresholds, not trade triggers.
    """
    md = current.get("market_data") or current
    ltp = _value(md, "ltp")
    instrument_key = str(current.get("instrument_key") or md.get("instrument_key") or "")
    if ltp <= 0 or not instrument_key or len(history) < 2:
        return None

    prices = [_value((x.get("market_data") or x), "ltp") for x in history]
    prices = [p for p in prices if p > 0]
    if len(prices) < 2:
        return None

    p1 = prices[-1]
    p3 = prices[-3] if len(prices) >= 3 else prices[0]
    p5 = prices[0]
    move_1m = _pct(ltp, p1)
    move_3m = _pct(ltp, p3)
    move_5m = _pct(ltp, p5)
    velocity = move_1m
    previous_velocity = _pct(p1, prices[-2]) if len(prices) >= 2 and prices[-2] > 0 else 0.0
    acceleration = velocity - previous_velocity

    volumes = [_value((x.get("market_data") or x), "volume") for x in history]
    current_volume = _value(md, "volume")
    avg_volume = sum(v for v in volumes[:-1] if v > 0) / max(1, sum(1 for v in volumes[:-1] if v > 0))
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

    early = score >= 55 and acceleration >= 0.5 and move_5m < 20.0
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
