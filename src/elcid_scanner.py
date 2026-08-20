from datetime import datetime
from zoneinfo import ZoneInfo

from src.elcid_full_valuation import LTP, CATEGORIES, NOTE6_NET, results as SCENARIO_RESULTS, ACCOUNTING_NAV, per_share

IST = ZoneInfo("Asia/Kolkata")


def scan_elcid():
    """Read-only ELCID portfolio/NAV scan. Never creates or modifies trades."""
    reported_nav_per_share = per_share(ACCOUNTING_NAV)
    market_price = LTP
    discount_to_reported_nav = (DecimalOne - (market_price / reported_nav_per_share)) * DecimalHundred
    base = SCENARIO_RESULTS["BASE"]
    bear = SCENARIO_RESULTS["BEAR"]
    bull = SCENARIO_RESULTS["BULL"]

    categories = []
    for name, value in CATEGORIES:
        categories.append({"name": name, "value_cr": float(value)})

    return {
        "stage": "ELCID",
        "timestamp": datetime.now(IST).isoformat(timespec="seconds"),
        "mode": "READ_ONLY",
        "orders_enabled": False,
        "ltp": float(market_price),
        "net_investment_cr": float(NOTE6_NET),
        "reported_nav_per_share": float(reported_nav_per_share),
        "market_discount_to_reported_nav_pct": float(discount_to_reported_nav),
        "categories": categories,
        "scenarios": {
            "BULL": {"nav_per_share": float(bull["value_per_share"])},
            "BASE": {"nav_per_share": float(base["value_per_share"])},
            "BEAR": {"nav_per_share": float(bear["value_per_share"])},
        },
    }


class _DecimalCompat:
    pass


# Keep arithmetic explicit without changing the valuation engine's constants.
from decimal import Decimal
DecimalOne = Decimal("1")
DecimalHundred = Decimal("100")
