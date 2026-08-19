"""Refresh the read-only hidden-value research universe.

The source bridge keeps ELCID on the verified live NAV engine and adds a small
curated holding-company watchlist from recent public market data. Watchlist
NAVs are explicitly screening NAVs derived from reported book value / P-B,
not audited SOTP NAVs. No catalyst is invented and no order API is called.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.elcid_live_nav import (  # noqa: E402
    ACCOUNTING_NAV_CR,
    SHARES,
    elcid_ltp,
    live_categories,
    live_sotp_nav_cr,
)

OUTPUT = ROOT / "data/hidden_value_source.csv"
FIELDS = [
    "symbol", "shares_outstanding", "market_price", "estimated_nav_cr",
    "listed_investments_cr", "cash_cr", "debt_cr", "deferred_tax_cr",
    "uncalled_commitment_cr", "other_liabilities_cr", "promoter_holding_pct",
    "free_float_pct", "avg_daily_value_cr", "corporate_action",
    "regulatory_catalyst", "special_auction", "restructuring_event",
    "revenue_growth_pct", "profit_growth_pct", "source_url", "source_name",
    "as_of_date",
]

# Public-data screening universe. estimated_nav_cr is derived as
# market_cap_cr / price_to_book, so it represents book-value NAV for screening,
# not a liquidation/SOTP valuation. These rows intentionally have no catalyst.
WATCHLIST = [
    {"symbol": "KALYANIINV", "market_cap_cr": 2420.0, "market_price": 5537.0, "price_to_book": 0.21,
     "source_url": "https://www.screener.in/company/id/1697/consolidated/", "source_name": "Screener public snapshot — book-value NAV screen"},
    {"symbol": "NALWASONS", "market_cap_cr": 2847.0, "market_price": 5539.0, "price_to_book": 0.18,
     "source_url": "https://www.screener.in/company/532256/consolidated/", "source_name": "Screener public snapshot — book-value NAV screen"},
    {"symbol": "PILANIINVS", "market_cap_cr": 4818.0, "market_price": 4351.0, "price_to_book": 0.30,
     "source_url": "https://www.screener.in/company/PILANIINVS/consolidated/", "source_name": "Screener public snapshot — book-value NAV screen"},
    {"symbol": "JSWHL", "market_cap_cr": 12270.0, "market_price": 11051.0, "price_to_book": 0.37,
     "source_url": "https://www.screener.in/company/532642/consolidated/", "source_name": "Screener public snapshot — book-value NAV screen"},
    {"symbol": "BFINVEST", "market_cap_cr": 1778.0, "market_price": 472.0, "price_to_book": 0.21,
     "source_url": "https://www.screener.in/company/533303/consolidated/", "source_name": "Screener public snapshot — book-value NAV screen"},
]


def _screening_row(item: dict, as_of: str) -> dict:
    nav = item["market_cap_cr"] / item["price_to_book"]
    return {
        "symbol": item["symbol"],
        "shares_outstanding": "",
        "market_price": item["market_price"],
        "estimated_nav_cr": round(nav, 2),
        "listed_investments_cr": "",
        "cash_cr": "", "debt_cr": "", "deferred_tax_cr": "",
        "uncalled_commitment_cr": "", "other_liabilities_cr": "",
        "promoter_holding_pct": "", "free_float_pct": "", "avg_daily_value_cr": "",
        "corporate_action": "", "regulatory_catalyst": "", "special_auction": "",
        "restructuring_event": "", "revenue_growth_pct": "", "profit_growth_pct": "",
        "source_url": item["source_url"], "source_name": item["source_name"],
        "as_of_date": as_of,
    }


def _verified_elcid_row(as_of: str) -> dict:
    listed = live_categories["Asian Paints"] + live_categories["Other quoted equity"]
    return {
        "symbol": "ELCIDINVESTMENTS",
        "shares_outstanding": float(SHARES), "market_price": float(elcid_ltp),
        "estimated_nav_cr": float(live_sotp_nav_cr), "listed_investments_cr": float(listed),
        "cash_cr": 0.0, "debt_cr": 0.0, "deferred_tax_cr": 0.0,
        "uncalled_commitment_cr": 0.0, "other_liabilities_cr": 0.0,
        "promoter_holding_pct": "", "free_float_pct": "", "avg_daily_value_cr": "",
        "corporate_action": "", "regulatory_catalyst": "", "special_auction": "",
        "restructuring_event": "", "revenue_growth_pct": "", "profit_growth_pct": "",
        "source_url": "src/elcid_live_nav.py", "source_name": "PEREZ AI verified live ELCID NAV engine",
        "as_of_date": as_of,
    }


def refresh(output_path: Path = OUTPUT) -> int:
    as_of = datetime.now(timezone.utc).date().isoformat()
    rows = [_verified_elcid_row(as_of)]
    rows.extend(_screening_row(item, as_of) for item in WATCHLIST)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    count = refresh()
    print(f"HIDDEN-VALUE SOURCE ROWS: {count}")
    print(f"ELCIDIN LTP: {elcid_ltp}")
    print(f"LIVE SOTP NAV: {live_sotp_nav_cr} Cr")
    print(f"ACCOUNTING NAV ANCHOR: {ACCOUNTING_NAV_CR} Cr")
    print("WATCHLIST NAV TYPE: BOOK-VALUE SCREENING NAV (NOT AUDITED SOTP)")
    print("ORDERS ENABLED: FALSE")
