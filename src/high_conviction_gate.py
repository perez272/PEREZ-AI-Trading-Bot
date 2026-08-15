MIN_HIGH_CONVICTION_SCORE = 80
REQUIRE_CATALYST = True

from src.hidden_value_detector import HiddenValueInput, calculate_hidden_value_score

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

    normal_pass = (
        r["score"] >= MIN_SCORE
        and r["nav_discount_pct"] >= MIN_NAV_DISCOUNT
        and asset_ratio >= MIN_ASSET_RATIO
    )
    catalyst = any(x.corporate_action for _ in [0]) or x.regulatory_catalyst or x.special_auction or x.restructuring_event
    exceptional_value = (
        r["score"] >= ELCID_EXCEPTION_SCORE
        and r["nav_discount_pct"] >= ELCID_EXCEPTION_NAV
        and asset_ratio >= ELCID_EXCEPTION_ASSETS
        and catalyst
    )
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

if __name__ == "__main__":
    elcid = {
        "symbol": "ELCIDINVESTMENTS",
        "market_cap_cr": 300,
        "estimated_nav_cr": 8000,
        "listed_investments_cr": 7000,
        "cash_cr": 0,
        "debt_cr": 0,
        "promoter_holding_pct": 74,
        "free_float_pct": 26,
        "avg_daily_value_cr": 0.01,
        "corporate_action": True,
        "regulatory_catalyst": True,
        "special_auction": True,
    }

    r = evaluate(elcid)

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
