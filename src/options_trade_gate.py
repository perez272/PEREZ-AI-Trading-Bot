from dataclasses import dataclass
from typing import Dict, List

from src.upgrade_config import OPTIONS_MIN_SCORE, MAX_SPREAD_PCT, MAX_SLIPPAGE_PCT

STOP_LOSS_PCT = 2.0
TARGETS = (5.0, 10.0, 15.0, 20.0)
MIN_SCORE = OPTIONS_MIN_SCORE

@dataclass
class OptionEvidence:
    symbol: str
    option_type: str
    expiry: str
    ltp: float
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    vwap_score: float = 0.0
    volatility_score: float = 0.0
    structure_score: float = 0.0
    oi_score: float = 0.0
    oi_change_score: float = 0.0
    iv_score: float = 0.0
    liquidity_score: float = 0.0
    index_confirmation: float = 0.0
    news_confirmation: float = 0.0
    event_risk_penalty: float = 0.0
    spread_pct: float = 0.0
    slippage_pct: float = 0.0
    underlying_signal: str = ""
    mtf_direction: str = ""


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def calculate_score(e: OptionEvidence) -> Dict:
    components = {
        "trend": clamp(e.trend_score, 0, 15), "momentum": clamp(e.momentum_score, 0, 10),
        "volume": clamp(e.volume_score, 0, 8), "vwap": clamp(e.vwap_score, 0, 7),
        "volatility": clamp(e.volatility_score, 0, 5), "structure": clamp(e.structure_score, 0, 5),
        "oi": clamp(e.oi_score, 0, 10), "oi_change": clamp(e.oi_change_score, 0, 8),
        "iv": clamp(e.iv_score, 0, 5), "liquidity": clamp(e.liquidity_score, 0, 7),
        "index_confirmation": clamp(e.index_confirmation, 0, 8),
        "news_confirmation": clamp(e.news_confirmation, 0, 5),
    }
    return {"score": round(clamp(sum(components.values()) - clamp(e.event_risk_penalty, 0, 20), 0, 100), 2), "components": components}


def projected_levels(entry: float) -> Dict:
    entry = float(entry)
    if entry <= 0:
        raise ValueError("Invalid option entry price")
    return {
        "entry": round(entry, 2),
        "stop_loss": round(entry * (1 - STOP_LOSS_PCT / 100), 2),
        **{f"T{i+1}_{pct:.0f}%": round(entry * (1 + pct / 100), 2) for i, pct in enumerate(TARGETS)},
    }


def validate_trade(e: OptionEvidence) -> Dict:
    reasons: List[str] = []
    if e.ltp <= 0: reasons.append("INVALID_LTP")
    if e.option_type.upper() not in {"CE", "PE"}: reasons.append("INVALID_OPTION_TYPE")
    if not e.expiry: reasons.append("MISSING_EXPIRY")
    if e.spread_pct > MAX_SPREAD_PCT: reasons.append("WIDE_SPREAD")
    if e.slippage_pct > MAX_SLIPPAGE_PCT: reasons.append("HIGH_SLIPPAGE")
    if e.volume_score <= 0: reasons.append("NO_LIVE_OPTION_VOLUME")
    if e.oi_score <= 0: reasons.append("NO_LIVE_OPTION_OI")

    # Direction is a hard gate, not a score bonus. A bullish underlying may
    # not authorize a PE and a bearish underlying may not authorize a CE.
    expected_direction = {"BUY CE": "BULLISH", "BUY PE": "BEARISH"}.get(e.underlying_signal.upper())
    if expected_direction and e.mtf_direction.upper() != expected_direction:
        reasons.append("MTF_DIRECTION_MISMATCH")
    if e.underlying_signal.upper() not in {"BUY CE", "BUY PE"}:
        reasons.append("MISSING_UNDERLYING_SIGNAL")
    if expected_direction == "BULLISH" and e.option_type.upper() != "CE":
        reasons.append("CE_PE_DIRECTION_MISMATCH")
    if expected_direction == "BEARISH" and e.option_type.upper() != "PE":
        reasons.append("CE_PE_DIRECTION_MISMATCH")

    # Require independent option evidence. A large positive percent change
    # alone must never be sufficient to manufacture a high score.
    option_evidence = e.trend_score + e.momentum_score + e.vwap_score
    if option_evidence < 12:
        reasons.append("WEAK_OPTION_DIRECTIONAL_EVIDENCE")
    if e.liquidity_score <= 0:
        reasons.append("NO_LIVE_OPTION_LIQUIDITY")

    result = calculate_score(e)
    if result["score"] < MIN_SCORE: reasons.append(f"SCORE_BELOW_{MIN_SCORE}")
    if e.event_risk_penalty >= 10: reasons.append("HIGH_EVENT_RISK")
    if e.index_confirmation < 4: reasons.append("WEAK_INDEX_CONFIRMATION")

    levels = projected_levels(e.ltp) if e.ltp > 0 else {}
    return {
        "symbol": e.symbol, "option_type": e.option_type.upper(), "expiry": e.expiry,
        "score": result["score"], "eligible": not reasons,
        "decision": "PAPER TRADE CANDIDATE" if not reasons else "NO TRADE",
        "reasons": reasons, "levels": levels, "live_orders": False, "paper_trade": True,
    }


def rank_candidates(candidates):
    return sorted([validate_trade(x) for x in candidates], key=lambda x: (x["eligible"], x["score"]), reverse=True)


def print_candidate(r):
    print(f"{r['symbol']} {r['option_type']} | {r['score']}/100 | {r['decision']}")
    if r["reasons"]: print("REJECT:", ", ".join(r["reasons"]))
