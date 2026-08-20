import contextlib
import io
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

# The legacy valuation module prints a detailed report at import time. Suppress
# that output here so the dedicated ELCID stage owns its telemetry.
with contextlib.redirect_stdout(io.StringIO()):
    from src.elcid_full_valuation import (
        LTP,
        CATEGORIES,
        NOTE6_NET,
        results as SCENARIO_RESULTS,
        ACCOUNTING_NAV,
        per_share,
    )

IST = ZoneInfo("Asia/Kolkata")


def scan_elcid():
    """Read-only ELCID portfolio/NAV scan. Never creates or modifies trades."""
    reported_nav_per_share = per_share(ACCOUNTING_NAV)
    market_price = LTP
    discount_to_reported_nav = (Decimal("1") - (market_price / reported_nav_per_share)) * Decimal("100")

    categories = [
        {"name": name, "value_cr": float(value)}
        for name, value in CATEGORIES
    ]

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
            name: {"nav_per_share": float(data["value_per_share"])}
            for name, data in SCENARIO_RESULTS.items()
        },
    }
