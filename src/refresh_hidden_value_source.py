"""Populate the hidden-value source from the existing verified ELCID live NAV engine.

This is deliberately conservative:
- reads current ELCIDIN/Asian Paints LTPs through the existing Angel One client;
- derives NAV and listed-investment value from the existing audited anchors;
- writes one auditable ELCID observation to hidden_value_source.csv;
- never creates an order or trade;
- does not invent a catalyst, so the high-conviction gate can reject the row when no
  verified current catalyst exists.

This is the source-population bridge. A broader ELCID-type universe still requires
independent, verified fundamental sources for each company rather than guessed data.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.elcid_live_nav import (
    AUDITED_CATEGORIES,
    ACCOUNTING_NAV_CR,
    SHARES,
    elcid_ltp,
    live_categories,
    live_sotp_nav_cr,
)

OUTPUT = Path("data/hidden_value_source.csv")

FIELDS = [
    "symbol", "shares_outstanding", "market_price", "estimated_nav_cr",
    "listed_investments_cr", "cash_cr", "debt_cr", "deferred_tax_cr",
    "uncalled_commitment_cr", "other_liabilities_cr", "promoter_holding_pct",
    "free_float_pct", "avg_daily_value_cr", "corporate_action",
    "regulatory_catalyst", "special_auction", "restructuring_event",
    "revenue_growth_pct", "profit_growth_pct", "source_url", "source_name",
    "as_of_date",
]


def build_verified_elcid_row() -> dict:
    # Listed-investment value is the live value of quoted listed holdings in the
    # existing ELCID SOTP model. We do not count unquoted/fund assets as listed.
    listed = (
        live_categories["Asian Paints"]
        + live_categories["Other quoted equity"]
    )

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
        # Never manufacture a catalyst. The high-conviction gate requires one.
        "corporate_action": "",
        "regulatory_catalyst": "",
        "special_auction": "",
        "restructuring_event": "",
        "revenue_growth_pct": "",
        "profit_growth_pct": "",
        # Existing live NAV engine is the auditable source for these values.
        "source_url": "src/elcid_live_nav.py",
        "source_name": "PEREZ AI verified live ELCID NAV engine",
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
    }


def refresh(output_path: Path = OUTPUT) -> int:
    row = build_verified_elcid_row()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return 1


if __name__ == "__main__":
    count = refresh()
    print(f"VERIFIED HIDDEN-VALUE SOURCE ROWS: {count}")
    print(f"ELCIDIN LTP: {elcid_ltp}")
    print(f"LIVE SOTP NAV: {live_sotp_nav_cr} Cr")
    print(f"ACCOUNTING NAV ANCHOR: {ACCOUNTING_NAV_CR} Cr")
    print("ORDERS ENABLED: FALSE")
