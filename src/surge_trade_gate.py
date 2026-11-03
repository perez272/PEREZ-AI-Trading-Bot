"""Evidence-based, multi-stage selector for early explosive option moves.

The legacy 0-100 surge score is retained as a ranking signal, not a win
probability. Entry eligibility also requires independent continuation,
market-direction, quote-quality, affordability and portfolio-risk checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.surge_confirmation import confirm
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
    """Retain the existing score weights; it measures surge intensity only."""
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
        "low_volume_penalty": -10.0 if 0.0 < e.volume_ratio < 1.1 else 0.0,
    }
    score = min(100.0, max(0.0, sum(components.values())))
    return {"score": round(score, 2), "components": components}


def validate_surge(e: SurgeEvidence, max_premium: float) -> dict[str, Any]:
    """Run independent evidence stages without changing existing numeric limits."""
    reasons: list[str] = []

    # Stage 1: contract identity and usable market data.
    identity_reasons: list[str] = []
    if e.option_type not in {"CE", "PE"}:
        identity_reasons.append("INVALID_OPTION_TYPE")
    if not e.instrument_key:
        identity_reasons.append("MISSING_INSTRUMENT_KEY")
    if not e.expiry:
        identity_reasons.append("MISSING_EXPIRY")
    if e.strike <= 0:
        identity_reasons.append("INVALID_STRIKE")
    if e.ltp <= 0:
        identity_reasons.append("INVALID_LTP")
    if e.bid <= 0 or e.ask <= 0 or e.ask < e.bid:
        identity_reasons.append("INVALID_ORDER_BOOK")
    reasons.extend(identity_reasons)

    # Stage 2: option-side momentum and participation.
    momentum_reasons: list[str] = []
    if e.volume <= 0:
        momentum_reasons.append("NO_LIVE_OPTION_VOLUME")
    if e.oi <= 0:
        momentum_reasons.append("NO_LIVE_OPTION_OI")
    if e.acceleration < 0.5:
        momentum_reasons.append("INSUFFICIENT_ACCELERATION")
    if e.move_5m_pct <= 0:
        momentum_reasons.append("NO_POSITIVE_5M_MOVE")
    if e.move_1m_pct <= 0:
        momentum_reasons.append("NO_POSITIVE_1M_MOVE")
    if e.detector_score >= 90.0 and e.move_5m_pct >= 6.0:
        momentum_reasons.append("OVEREXTENDED_SURGE")
    reasons.extend(momentum_reasons)

    # Stage 3: executable quote quality. Keep configured limits unchanged.
    execution_reasons: list[str] = []
    if e.spread_pct > MAX_SPREAD_PCT:
        execution_reasons.append("WIDE_SPREAD")
    if e.slippage_pct > MAX_SLIPPAGE_PCT:
        execution_reasons.append("HIGH_SLIPPAGE")
    reasons.extend(execution_reasons)

    scoring = calculate_surge_score(e)
    if scoring["score"] < 55.0:
        reasons.append("SURGE_SCORE_BELOW_55")

    # Stage 4: independent continuation evidence. This existing, historically
    # derived confirmation model is now wired into the actual entry path.
    continuation = confirm({
        "move_1m_pct": e.move_1m_pct,
        "move_3m_pct": e.move_3m_pct,
        "move_5m_pct": e.move_5m_pct,
        "acceleration": e.acceleration,
        "spread_pct": e.spread_pct,
        "volume_ratio": e.volume_ratio,
        "score": e.detector_score,
    })
    if not continuation["confirmed"]:
        reasons.append("SURGE_CONTINUATION_NOT_CONFIRMED")

    stages = {
        "contract_and_data": {"passed": not identity_reasons, "reasons": identity_reasons},
        "option_momentum": {"passed": not momentum_reasons, "reasons": momentum_reasons},
        "execution_quality": {"passed": not execution_reasons, "reasons": execution_reasons},
        "continuation": continuation,
        "portfolio_risk": {
            "status": "PENDING_EXISTING_RISK_AND_ATOMIC_RESERVATION_GATES",
            "note": "Not evaluated or bypassed by this selector.",
        },
    }
    eligible = not reasons
    return {
        "score": scoring["score"],
        "score_role": "SURGE_INTENSITY_RANKING_NOT_WIN_PROBABILITY",
        "components": scoring["components"],
        "stages": stages,
        "eligible": eligible,
        "decision": "SURGE PAPER TRADE CANDIDATE" if eligible else "NO TRADE",
        "reasons": reasons,
    }
