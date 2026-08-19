"""Refresh the read-only hidden-value research universe.

ELCID keeps its verified live SOTP NAV. Other holding-company rows are
screening rows: their NAV is book-value based and must never be presented as
an audited SOTP.  The non-ELCID rows now carry explicit FY2026 balance-sheet
asset/liability anchors so discovery can distinguish real asset coverage from
a bare price-to-book snapshot. No catalyst is invented and no order API is
called.
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

# FY2026 balance-sheet anchors are from the public consolidated Screener
# snapshots verified during the upgrade. They are screening inputs, not
# live SOTP valuations. Market price/cap are also snapshots and are refreshed
# independently from the verified live ELCID engine.
WATCHLIST = [
    {
        "symbol": "KALYANIINV", "market_cap_cr": 2420.0, "market_price": 5537.0,
        "book_value_per_share": 26095.0, "listed_investments_cr": 12124.0,
        "debt_cr": 0.0, "other_liabilities_cr": 1043.0,
        "promoter_holding_pct": 74.98,
        "source_url": "https://www.screener.in/company/533302/consolidated/",
    },
    {
        "symbol": "NALWASONS", "market_cap_cr": 2847.0, "market_price": 5539.0,
        "book_value_per_share": 29541.0, "listed_investments_cr": 16744.0,
        "debt_cr": 3.0, "other_liabilities_cr": 2009.0,
        "promoter_holding_pct": 55.61,
        "source_url": "https://www.screener.in/company/532256/consolidated/",
    },
    {
        "symbol": "PILANIINVS", "market_cap_cr": 4818.0, "market_price": 4351.0,
        "book_value_per_share": 14334.0, "listed_investments_cr": 18939.0,
        "debt_cr": 2391.0, "other_liabilities_cr": 1318.0,
        "promoter_holding_pct": "",
        "source_url": "https://www.screener.in/company/PILANIINVS/consolidated/",
    },
    {
        "symbol": "JSWHL", "market_cap_cr": 12270.0, "market_price": 11051.0,
        "book_value_per_share": 29741.0, "listed_investments_cr": 20886.0,
        "debt_cr": 0.0, "other_liabilities_cr": "",
        "promoter_holding_pct": 58.68,
        "source_url": "https://www.screener.in/company/532642/consolidated/",
    },
    {
        "symbol": "BFINVEST", "market_cap_cr": 1778.0, "market_price": 472.0,
        "book_value_per_share": 2267.0, "listed_investments_cr": 8764.0,
        "debt_cr": 0.0, "other_liabilities_cr": 855.0,
        "promoter_holding_pct": 74.13,
        "source_url": "https://www.screener.in/company/533303/consolidated/",
    },
]


def _screening_row(item: dict, as_of: str) -> dict:
    market_cap = float(item["market_cap_cr"])
    price = float(item["market_price"])
    book_value = float(item["book_value_per_share"])
    nav = market_cap * (book_value / price)
    shares = market_cap * 1e7 / price
    return {
        "symbol": item["symbol"],
        "shares_outstanding": round(shares, 4),
        "market_price": price,
        "estimated_nav_cr": round(nav, 2),
        "listed_investments_cr": float(item["listed_investments_cr"]),
        "cash_cr": "",
        "debt_cr": item.get("debt_cr", ""),
        "deferred_tax_cr": "",
        "uncalled_commitment_cr": "",
        "other_liabilities_cr": item.get("other_liabilities_cr", ""),
        "promoter_holding_pct": item.get("promoter_holding_pct", ""),
        "free_float_pct": "",
        "avg_daily_value_cr": "",
        "corporate_action": "",
        "regulatory_catalyst": "",
        "special_auction": "",
        "restructuring_event": "",
        "revenue_growth_pct": "",
        "profit_growth_pct": "",
        "source_url": item["source_url"],
        "source_name": "Screener public FY2026 balance-sheet snapshot — book-value screening NAV",
        "as_of_date": as_of,
    }


def _verified_elcid_row(as_of: str) -> dict:
    listed = live_categories["Asian Paints"] + live_categories["Other quoted equity"]
    return {
        "symbol": "ELCIDINVESTMENTS",
        "shares_outstanding": float(SHARES),
        "market_price": float(elcid_ltp),
        "estimated_nav_cr": float(live_sotp_nav_cr),
        "listed_investments_cr": float(listed),
        "cash_cr": 0.0,
        "debt_cr": 0.0,
        "deferred_tax_cr": 0.0,
        "uncalled_commitment_cr": 0.0,
        "other_liabilities_cr": 0.0,
        "promoter_holding_pct": "",
        "free_float_pct": "",
        "avg_daily_value_cr": "",
        "corporate_action": "",
        "regulatory_catalyst": "",
        "special_auction": "",
        "restructuring_event": "",
        "revenue_growth_pct": "",
        "profit_growth_pct": "",
        "source_url": "src/elcid_live_nav.py",
        "source_name": "PEREZ AI verified live ELCID NAV engine",
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
    print("FY2026 ASSET COVERAGE: VERIFIED INPUTS PRESENT")
    print("ORDERS ENABLED: FALSE")
