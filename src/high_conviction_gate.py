"""Strict read-only high-conviction admission gate."""
import csv
from pathlib import Path

from src.hidden_value_detector import HiddenValueInput, calculate_hidden_value_score

MIN_HIGH_CONVICTION_SCORE = 80
REQUIRE_CATALYST = True
MIN_SCORE = 80
MIN_NAV_DISCOUNT = 50.0
MIN_ASSET_RATIO = 3.0
ELCID_EXCEPTION_SCORE = 80
ELCID_EXCEPTION_NAV = 90.0
ELCID_EXCEPTION_ASSETS = 10.0


def evaluate(data):
    x = HiddenValueInput(**data)
    r = calculate_hidden_value_score(x)

    market_cap = max(float(x.market_cap_cr), 0.0)
    listed_assets = max(float(x.listed_investments_cr), 0.0)
    asset_ratio = listed_assets / market_cap if market_cap else 0.0

    catalyst = bool(x.corporate_action or x.regulatory_catalyst or x.special_auction or x.restructuring_event)
    hard_pass = (
        r["score"] >= MIN_HIGH_CONVICTION_SCORE
        and r["nav_discount_pct"] >= MIN_NAV_DISCOUNT
        and asset_ratio >= MIN_ASSET_RATIO
        and catalyst
    )

    return {
        **r,
        "asset_ratio": round(asset_ratio, 2),
        "HIGH_CONVICTION": hard_pass,
        "SAFE_MODE": True,
        "ORDERS_ENABLED": False,
    }


def _demo_row():
    """Use the canonical candidate universe for diagnostics, not hardcoded values."""
    path = Path("data/hidden_value_candidates.csv")
    if not path.exists():
        path = Path("data/hidden_value_source.csv")
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if str(row.get("symbol") or "").strip().upper() == "ELCIDINVESTMENTS":
            return {
                "symbol": "ELCIDINVESTMENTS",
                "market_cap_cr": float(row.get("market_cap_cr") or 0),
                "estimated_nav_cr": float(row.get("estimated_nav_cr") or 0),
                "listed_investments_cr": float(row.get("listed_investments_cr") or 0),
                "cash_cr": float(row.get("cash_cr") or 0),
                "debt_cr": float(row.get("debt_cr") or 0),
                "promoter_holding_pct": float(row.get("promoter_holding_pct") or 0),
                "free_float_pct": float(row.get("free_float_pct") or 0),
                "avg_daily_value_cr": float(row.get("avg_daily_value_cr") or 0),
                "corporate_action": str(row.get("corporate_action") or "").lower() == "true",
                "regulatory_catalyst": str(row.get("regulatory_catalyst") or "").lower() == "true",
                "special_auction": str(row.get("special_auction") or "").lower() == "true",
                "restructuring_event": str(row.get("restructuring_event") or "").lower() == "true",
                "revenue_growth_pct": float(row.get("revenue_growth_pct") or 0),
                "profit_growth_pct": float(row.get("profit_growth_pct") or 0),
            }
    return None


if __name__ == "__main__":
    data = _demo_row()
    if data is None:
        print("PEREZ AI — HIGH-CONVICTION ELCID GATE")
        print("NO ELCID CANDIDATE DATA AVAILABLE")
    else:
        r = evaluate(data)
        print("PEREZ AI — HIGH-CONVICTION ELCID GATE")
        print("======================================")
        print(f"Symbol             : {r['symbol']}")
        print(f"Score              : {r['score']}/100")
        print(f"NAV Discount       : {r['nav_discount_pct']}%")
        print(f"Listed Asset Ratio : {r['asset_ratio']}x")
        print(f"Classification     : {r['classification']}")
        print(f"HIGH CONVICTION    : {r['HIGH_CONVICTION']}")
        print(f"SAFE MODE          : {r['SAFE_MODE']}")
        print(f"ORDERS ENABLED     : {r['ORDERS_ENABLED']}")
