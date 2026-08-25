"""Low-latency Tier-1 option explosive-move detector.

Observational/paper-only signal layer. It detects acceleration BEFORE a large
option move is complete; it never places orders and never overrides risk gates.
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
    oi_change_pct: float = 0.0
    iv_change_pct: float = 0.0
    delta_change: float = 0.0
    gamma_change: float = 0.0
    spot_change_pct: float = 0.0
    futures_change_pct: float = 0.0
    distance_to_spot_pct: float = 0.0
    minutes_to_expiry: float = 0.0
    precursor_score: float = 0.0


def _pct(now: float, old: float) -> float:
    return ((now - old) / old * 100.0) if old > 0 else 0.0


def _value(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _series_change(current: dict[str, Any], history: list[dict[str, Any]], key: str) -> float:
    now = _value(current, key)
    old = 0.0
    for item in history:
        old = _value(item, key)
        if old != 0:
            break
    return _pct(now, old) if old != 0 else 0.0


def _nested(row: dict[str, Any], key: str) -> float:
    md = row.get("market_data") or {}
    greeks = row.get("option_greeks") if isinstance(row.get("option_greeks"), dict) else {}
    return _value(row, key, _value(md, key, _value(greeks, key)))


def detect_explosive_move(symbol: str, option_type: str, current: dict[str, Any], history: list[dict[str, Any]]) -> ExplosiveMoveSignal | None:
    """Detect early acceleration plus richer option/underlying precursor evidence.

    history is oldest -> newest and should contain observations no older than 5 minutes.
    Thresholds remain research/precursor thresholds, not trade triggers.
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

    oi_change_pct = _series_change(current, history, "open_interest")
    if oi_change_pct == 0:
        oi_change_pct = _series_change(current, history, "oi")
    iv_change_pct = _series_change(current, history, "iv")
    delta_now = _nested(current, "delta")
    delta_old = _nested(history[-1], "delta") if history else 0.0
    gamma_now = _nested(current, "gamma")
    gamma_old = _nested(history[-1], "gamma") if history else 0.0
    delta_change = delta_now - delta_old if delta_old or delta_now else 0.0
    gamma_change = gamma_now - gamma_old if gamma_old or gamma_now else 0.0
    spot_change_pct = _series_change(current, history, "spot_ltp")
    futures_change_pct = _series_change(current, history, "futures_ltp")
    distance_to_spot_pct = _value(current, "distance_to_spot_pct")
    minutes_to_expiry = _value(current, "minutes_to_expiry")

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

    # Rich evidence is additive and only scores when the field is genuinely available.
    precursor = score
    if oi_change_pct >= 10:
        precursor += 8; reasons.append("oi_expansion")
    if iv_change_pct >= 5:
        precursor += 7; reasons.append("iv_expansion")
    if abs(gamma_change) > 0:
        precursor += 5; reasons.append("gamma_change")
    if abs(delta_change) >= 0.03:
        precursor += 5; reasons.append("delta_shift")
    if abs(spot_change_pct) >= 0.15:
        precursor += 7; reasons.append("underlying_acceleration")
    if abs(futures_change_pct) >= 0.15:
        precursor += 5; reasons.append("futures_confirmation")
    if minutes_to_expiry > 0 and minutes_to_expiry <= 180:
        precursor += 5; reasons.append("near_expiry")

    precursor = max(0.0, min(100.0, precursor))
    early = precursor >= 55 and acceleration >= 0.5 and move_5m < 20.0
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
        oi_change_pct=round(oi_change_pct, 4),
        iv_change_pct=round(iv_change_pct, 4),
        delta_change=round(delta_change, 6),
        gamma_change=round(gamma_change, 6),
        spot_change_pct=round(spot_change_pct, 4),
        futures_change_pct=round(futures_change_pct, 4),
        distance_to_spot_pct=round(distance_to_spot_pct, 4),
        minutes_to_expiry=round(minutes_to_expiry, 2),
        precursor_score=round(precursor, 2),
    )
