"""Dedicated gate for early explosive option moves.

Surge scoring is independent from the normal directional options score.
It never bypasses affordability, capital, trade-count, or risk controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from src.upgrade_config import OPTION_MAX_PREMIUM, MAX_SPREAD_PCT, MAX_SLIPPAGE_PCT


@dataclass(frozen=True)
class SurgeEvidence:
    symbol: str
    option_type: str
    instrument_key: str
    expiry: str
    strike: float
    ltp: float
    bid: float
    ask: float
    volume: float
    oi: float
    iv: float
    move_1m_pct: float
    move_3m_pct: float
    move_5m_pct: float
    velocity: float
    acceleration: float
    volume_ratio: float
    spread_pct: float
    slippage_pct: float
    detector_score: float


def calculate_surge_score(e: SurgeEvidence) -> dict[str, Any]:
    """Score time-series explosive evidence, not normal directional evidence."""
    components = {
        "detector": min(25.0, max(0.0, e.detector_score * 0.25)),
        "move_1m": min(15.0, max(0.0, e.move_1m_pct / 1.5 * 15.0)),
        "move_3m": min(15.0, max(0.0, e.move_3m_pct / 2.5 * 15.0)),
        "move_5m": min(10.0, max(0.0, e.move_5m_pct / 4.0 * 10.0)),
        "velocity": min(8.0, max(0.0, e.velocity / 1.0 * 8.0)),
        "acceleration": min(10.0, max(0.0, e.acceleration / 0.75 * 10.0)),
        "volume": min(7.0, max(0.0, (e.volume_ratio - 1.0) / 0.5 * 7.0)),
        "liquidity": 5.0 if e.volume > 0 and e.oi > 0 else 0.0,
        "iv": 2.0 if e.iv > 0 else 0.0,
        "spread": 3.0 if e.spread_pct <= MAX_SPREAD_PCT else 0.0,
    }
    score = min(100.0, max(0.0, sum(components.values())))
    return {"score": round(score, 2), "components": components}


def validate_surge(e: SurgeEvidence, max_premium: float) -> dict[str, Any]:
    """Validate an early surge without using the normal options score."""
    reasons: list[str] = []

    if e.option_type not in {"CE", "PE"}:
        reasons.append("INVALID_OPTION_TYPE")
    if not e.instrument_key:
        reasons.append("MISSING_INSTRUMENT_KEY")
    if not e.expiry:
        reasons.append("MISSING_EXPIRY")
    if e.strike <= 0:
        reasons.append("INVALID_STRIKE")
    if e.ltp <= 0:
        reasons.append("INVALID_LTP")
    if e.ltp > max_premium:
        reasons.append("PREMIUM_ABOVE_LIMIT")
    if e.bid <= 0 or e.ask <= 0 or e.ask < e.bid:
        reasons.append("INVALID_ORDER_BOOK")
    if e.volume <= 0:
        reasons.append("NO_LIVE_OPTION_VOLUME")
    if e.oi <= 0:
        reasons.append("NO_LIVE_OPTION_OI")
    if e.spread_pct > MAX_SPREAD_PCT:
        reasons.append("WIDE_SPREAD")
    if e.slippage_pct > MAX_SLIPPAGE_PCT:
        reasons.append("HIGH_SLIPPAGE")
    if e.acceleration < 0.5:
        reasons.append("INSUFFICIENT_ACCELERATION")
    if e.move_5m_pct <= 0:
        reasons.append("NO_POSITIVE_5M_MOVE")

    scoring = calculate_surge_score(e)

    if scoring["score"] < 55.0:
        reasons.append("SURGE_SCORE_BELOW_55")

    return {
        "score": scoring["score"],
        "components": scoring["components"],
        "eligible": not reasons,
        "decision": "SURGE PAPER TRADE CANDIDATE" if not reasons else "NO TRADE",
        "reasons": reasons,
    }
