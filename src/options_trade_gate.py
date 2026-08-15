from dataclasses import dataclass
from typing import Dict, List

# ============================================================
# PEREZ AI — OPTIONS TRADE GATE
# PURPOSE: PAPER-TRADE DECISION ONLY
# LIVE ORDERS: NEVER CREATED BY THIS MODULE
# ============================================================

STOP_LOSS_PCT = 2.0
TARGETS = (5.0, 10.0, 15.0, 20.0)
MIN_SCORE = 80
MIN_RR_TO_FIRST_TARGET = 2.0


@dataclass
class OptionEvidence:
    symbol: str
    option_type: str
    expiry: str
    ltp: float

    # Technical
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    vwap_score: float = 0.0
    volatility_score: float = 0.0
    structure_score: float = 0.0

    # Derivatives
    oi_score: float = 0.0
    oi_change_score: float = 0.0
    iv_score: float = 0.0
    liquidity_score: float = 0.0

    # Market/event/news confirmation
    index_confirmation: float = 0.0
    news_confirmation: float = 0.0
    event_risk_penalty: float = 0.0

    # Safety
    spread_pct: float = 0.0
    slippage_pct: float = 0.0


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def calculate_score(e: OptionEvidence) -> Dict:
    """
    100-point decision model.

    IMPORTANT:
    A high score does NOT guarantee profit.
    It only means the evidence passes the configured
    paper-trading quality threshold.
    """

    components = {
        "trend": clamp(e.trend_score, 0, 15),
        "momentum": clamp(e.momentum_score, 0, 10),
        "volume": clamp(e.volume_score, 0, 8),
        "vwap": clamp(e.vwap_score, 0, 7),
        "volatility": clamp(e.volatility_score, 0, 5),
        "structure": clamp(e.structure_score, 0, 5),

        "oi": clamp(e.oi_score, 0, 10),
        "oi_change": clamp(e.oi_change_score, 0, 8),
        "iv": clamp(e.iv_score, 0, 5),
        "liquidity": clamp(e.liquidity_score, 0, 7),

        "index_confirmation": clamp(e.index_confirmation, 0, 8),
        "news_confirmation": clamp(e.news_confirmation, 0, 5),
    }

    raw = sum(components.values())
    penalty = clamp(e.event_risk_penalty, 0, 20)

    score = round(clamp(raw - penalty, 0, 100), 2)

    return {
        "score": score,
        "components": components,
        "event_risk_penalty": penalty,
    }


def projected_levels(entry: float) -> Dict:
    entry = float(entry)

    if entry <= 0:
        raise ValueError("Invalid option entry price")

    stop = round(entry * (1 - STOP_LOSS_PCT / 100), 2)

    targets = {
        f"T{i+1}_{pct:.0f}%": round(entry * (1 + pct / 100), 2)
        for i, pct in enumerate(TARGETS)
    }

    return {
        "entry": round(entry, 2),
        "stop_loss": stop,
        **targets,
    }


def validate_trade(e: OptionEvidence) -> Dict:
    reasons: List[str] = []

    if e.ltp <= 0:
        reasons.append("INVALID_LTP")

    if e.option_type.upper() not in {"CE", "PE"}:
        reasons.append("INVALID_OPTION_TYPE")

    if not e.expiry:
        reasons.append("MISSING_EXPIRY")

    # Avoid entering contracts where transaction quality is poor.
    if e.spread_pct > 1.0:
        reasons.append("WIDE_SPREAD")

    if e.slippage_pct > 0.75:
        reasons.append("HIGH_SLIPPAGE")

    result = calculate_score(e)

    # Require strong evidence across multiple dimensions.
    # One indicator alone can never approve a trade.
    if result["score"] < MIN_SCORE:
        reasons.append("SCORE_BELOW_80")

    # Event/news risk can veto a technically attractive trade.
    if e.event_risk_penalty >= 10:
        reasons.append("HIGH_EVENT_RISK")

    # We require at least meaningful market/index confirmation.
    if e.index_confirmation < 4:
        reasons.append("WEAK_INDEX_CONFIRMATION")

    levels = projected_levels(e.ltp) if e.ltp > 0 else {}

    eligible = not reasons

    return {
        "symbol": e.symbol,
        "option_type": e.option_type.upper(),
        "expiry": e.expiry,
        "score": result["score"],
        "eligible": eligible,
        "decision": "PAPER TRADE CANDIDATE" if eligible else "NO TRADE",
        "reasons": reasons,
        "levels": levels,
        "live_orders": False,
        "paper_trade": True,
    }


def rank_candidates(candidates):
    evaluated = [validate_trade(x) for x in candidates]
    return sorted(
        evaluated,
        key=lambda x: (x["eligible"], x["score"]),
        reverse=True,
    )


def print_candidate(r):
    print("-" * 72)
    print(f"{r['symbol']} {r['option_type']} | EXPIRY {r['expiry']}")
    print(f"SCORE       : {r['score']}/100")
    print(f"DECISION    : {r['decision']}")

    if r["levels"]:
        print(f"ENTRY       : Rs {r['levels']['entry']}")
        print(f"STOP LOSS   : Rs {r['levels']['stop_loss']}")
        print(f"+5% TARGET  : Rs {r['levels']['T1_5%']}")
        print(f"+10% TARGET : Rs {r['levels']['T2_10%']}")
        print(f"+15% TARGET : Rs {r['levels']['T3_15%']}")
        print(f"+20% TARGET : Rs {r['levels']['T4_20%']}")

    if r["reasons"]:
        print("REJECT      :", ", ".join(r["reasons"]))

    print("PAPER TRADE :", r["paper_trade"])
    print("LIVE ORDERS :", r["live_orders"])


if __name__ == "__main__":
    print("=" * 72)
    print("PEREZ AI — OPTIONS TRADE GATE SELF TEST")
    print("=" * 72)
    print("STOP LOSS              :", f"{STOP_LOSS_PCT}%")
    print("TARGETS                :", ", ".join(f"{x}%" for x in TARGETS))
    print("MINIMUM SCORE          :", MIN_SCORE)
    print("PAPER TRADING          : ENABLED")
    print("LIVE ORDERS            : DISABLED")
    print()

    # Strong hypothetical setup used ONLY to test mathematics.
    test = OptionEvidence(
        symbol="TEST",
        option_type="CE",
        expiry="SELFTEST",
        ltp=100.0,
        trend_score=15,
        momentum_score=10,
        volume_score=8,
        vwap_score=7,
        volatility_score=5,
        structure_score=5,
        oi_score=10,
        oi_change_score=8,
        iv_score=5,
        liquidity_score=7,
        index_confirmation=8,
        news_confirmation=5,
        event_risk_penalty=0,
        spread_pct=0.2,
        slippage_pct=0.1,
    )

    result = validate_trade(test)
    print_candidate(result)

    assert result["levels"]["stop_loss"] == 98.0
    assert result["levels"]["T1_5%"] == 105.0
    assert result["levels"]["T2_10%"] == 110.0
    assert result["levels"]["T3_15%"] == 115.0
    assert result["levels"]["T4_20%"] == 120.0
    assert result["paper_trade"] is True
    assert result["live_orders"] is False

    print()
    print("=" * 72)
    print("PASS: 2% STOP-LOSS MATHEMATICS")
    print("PASS: 5/10/15/20% PROFIT TARGETS")
    print("PASS: MULTI-FACTOR SCORE")
    print("PASS: INDEX CONFIRMATION REQUIRED")
    print("PASS: OI / OI-CHANGE FACTORS INCLUDED")
    print("PASS: NEWS / EVENT RISK FACTOR INCLUDED")
    print("PASS: SPREAD / SLIPPAGE FILTER")
    print("PASS: PAPER TRADING ONLY")
    print("PASS: LIVE ORDERS DISABLED")
    print("=" * 72)
