"""
PEREZ AI — Hidden Value / Corporate Catalyst Detector
ELCID-style structural opportunity detector.

SAFE DESIGN:
- Standalone module
- Does NOT place orders
- Does NOT modify existing trade engine
- Does NOT modify paper positions
- Produces a 0-100 structural opportunity score
"""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class HiddenValueInput:
    symbol: str

    market_cap_cr: float = 0.0
    estimated_nav_cr: float = 0.0
    listed_investments_cr: float = 0.0
    cash_cr: float = 0.0
    debt_cr: float = 0.0

    promoter_holding_pct: float = 0.0
    free_float_pct: float = 100.0

    avg_daily_value_cr: float = 0.0

    corporate_action: bool = False
    regulatory_catalyst: bool = False
    special_auction: bool = False
    restructuring_event: bool = False

    revenue_growth_pct: float = 0.0
    profit_growth_pct: float = 0.0


def calculate_hidden_value_score(x: HiddenValueInput) -> dict:
    score = 0
    signals = []
    warnings = []

    market_cap = max(float(x.market_cap_cr), 0.0)
    nav = max(float(x.estimated_nav_cr), 0.0)

    # ---------------------------------------------------------
    # 1. NAV DISCOUNT — 25 POINTS
    # ---------------------------------------------------------
    nav_discount = 0.0

    if market_cap > 0 and nav > 0:
        nav_discount = max(0.0, 1.0 - market_cap / nav)

        if nav_discount >= 0.90:
            score += 25
            signals.append("EXTREME_NAV_DISCOUNT")
        elif nav_discount >= 0.75:
            score += 20
            signals.append("VERY_HIGH_NAV_DISCOUNT")
        elif nav_discount >= 0.50:
            score += 12
            signals.append("HIGH_NAV_DISCOUNT")
        elif nav_discount >= 0.30:
            score += 6
            signals.append("NAV_DISCOUNT")

    # ---------------------------------------------------------
    # 2. UNDERLYING LISTED ASSETS — 15 POINTS
    # ---------------------------------------------------------
    if market_cap > 0 and x.listed_investments_cr > 0:
        asset_ratio = x.listed_investments_cr / market_cap

        if asset_ratio >= 20:
            score += 15
            signals.append("EXTREME_LISTED_ASSET_DISLOCATION")
        elif asset_ratio >= 10:
            score += 12
            signals.append("VERY_HIGH_LISTED_ASSET_VALUE")
        elif asset_ratio >= 5:
            score += 8
            signals.append("HIGH_LISTED_ASSET_VALUE")
        elif asset_ratio >= 2:
            score += 4
            signals.append("LISTED_ASSETS_EXCEED_MARKET_CAP")

    # ---------------------------------------------------------
    # 3. CORPORATE / REGULATORY CATALYST — 20 POINTS
    # ---------------------------------------------------------
    if x.special_auction:
        score += 20
        signals.append("SPECIAL_AUCTION_CATALYST")
    elif x.regulatory_catalyst:
        score += 15
        signals.append("REGULATORY_CATALYST")
    elif x.corporate_action:
        score += 12
        signals.append("CORPORATE_ACTION")
    elif x.restructuring_event:
        score += 10
        signals.append("RESTRUCTURING_CATALYST")

    # ---------------------------------------------------------
    # 4. OWNERSHIP / FLOAT — 10 POINTS
    # ---------------------------------------------------------
    if x.promoter_holding_pct >= 75 and x.free_float_pct <= 25:
        score += 10
        signals.append("EXTREMELY_LOW_EFFECTIVE_FLOAT")
    elif x.promoter_holding_pct >= 50 and x.free_float_pct <= 40:
        score += 7
        signals.append("LOW_EFFECTIVE_FLOAT")
    elif x.free_float_pct <= 50:
        score += 4
        signals.append("REDUCED_FLOAT")

    # ---------------------------------------------------------
    # 5. LIQUIDITY ANOMALY — 10 POINTS
    # ---------------------------------------------------------
    if x.avg_daily_value_cr <= 0.05:
        score += 10
        signals.append("EXTREME_ILLIQUIDITY")
    elif x.avg_daily_value_cr <= 0.25:
        score += 7
        signals.append("VERY_LOW_LIQUIDITY")
    elif x.avg_daily_value_cr <= 1.0:
        score += 4
        signals.append("LOW_LIQUIDITY")

    # ---------------------------------------------------------
    # 6. FINANCIAL QUALITY — 10 POINTS
    # ---------------------------------------------------------
    if x.profit_growth_pct >= 20:
        score += 5
        signals.append("STRONG_PROFIT_GROWTH")
    elif x.profit_growth_pct > 0:
        score += 2

    if x.revenue_growth_pct >= 20:
        score += 5
        signals.append("STRONG_REVENUE_GROWTH")
    elif x.revenue_growth_pct > 0:
        score += 2

    # ---------------------------------------------------------
    # 7. BALANCE SHEET CHECK
    # ---------------------------------------------------------
    if x.debt_cr > x.cash_cr and x.debt_cr > 0:
        warnings.append("DEBT_EXCEEDS_CASH")

    if market_cap > 0 and nav <= 0:
        warnings.append("NAV_NOT_AVAILABLE")

    if market_cap <= 0:
        warnings.append("MARKET_CAP_NOT_AVAILABLE")

    score = min(100, max(0, score))

    if score >= 80:
        classification = "EXTREME_REPRICING_CANDIDATE"
    elif score >= 65:
        classification = "HIGH_PRIORITY_VALUE_EVENT"
    elif score >= 50:
        classification = "WATCHLIST"
    else:
        classification = "LOW_PRIORITY"

    return {
        "symbol": x.symbol,
        "score": score,
        "classification": classification,
        "nav_discount_pct": round(nav_discount * 100, 2),
        "signals": signals,
        "warnings": warnings,
        "paper_trade_only": True,
        "orders_enabled": False,
    }


def self_test():
    """
    Historical-style ELCID stress test.
    Values are intentionally approximate and are NOT a live valuation.
    """

    elcid = HiddenValueInput(
        symbol="ELCIDINVESTMENTS",
        market_cap_cr=300.0,
        estimated_nav_cr=8000.0,
        listed_investments_cr=7000.0,
        cash_cr=0.0,
        debt_cr=0.0,
        promoter_holding_pct=74.0,
        free_float_pct=26.0,
        avg_daily_value_cr=0.01,
        corporate_action=True,
        regulatory_catalyst=True,
        special_auction=True,
        restructuring_event=False,
        revenue_growth_pct=0.0,
        profit_growth_pct=0.0,
    )

    result = calculate_hidden_value_score(elcid)

    print("=" * 70)
    print("PEREZ AI — HIDDEN VALUE DETECTOR SELF TEST")
    print("=" * 70)
    print(f"Symbol       : {result['symbol']}")
    print(f"Score        : {result['score']}/100")
    print(f"Classification: {result['classification']}")
    print(f"NAV Discount : {result['nav_discount_pct']}%")
    print()
    print("Signals:")
    for signal in result["signals"]:
        print(f"  + {signal}")

    if result["warnings"]:
        print()
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"  ! {warning}")

    print()
    print(f"Paper Trade Only : {result['paper_trade_only']}")
    print(f"Orders Enabled   : {result['orders_enabled']}")
    print("=" * 70)

    assert result["score"] >= 75
    assert result["classification"] == "HIGH_PRIORITY_VALUE_EVENT"
    assert result["orders_enabled"] is False

    return result


if __name__ == "__main__":
    self_test()
