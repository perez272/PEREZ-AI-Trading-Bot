"""Audit-friendly source builder for the hidden-value universe.

This module intentionally does not invent NAVs or prices. It converts a supplied
list of already-verified observations into the canonical CSV input consumed by
hidden_value_data_pipeline.py.
"""
from pathlib import Path
import csv
from typing import Iterable

FIELDS = [
    "symbol", "shares_outstanding", "market_price", "estimated_nav_cr",
    "listed_investments_cr", "cash_cr", "debt_cr", "deferred_tax_cr",
    "uncalled_commitment_cr", "other_liabilities_cr", "promoter_holding_pct",
    "free_float_pct", "avg_daily_value_cr", "corporate_action",
    "regulatory_catalyst", "special_auction", "restructuring_event",
    "revenue_growth_pct", "profit_growth_pct", "source_url", "source_name",
    "as_of_date",
]


def write_verified_rows(rows: Iterable[dict], output: Path = Path("data/hidden_value_source.csv")) -> int:
    """Replace the source CSV with rows explicitly supplied by a trusted fetcher.

    No defaults are filled for valuation fields, so incomplete observations fail
    downstream validation instead of silently becoming trade candidates.
    """
    rows = list(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in FIELDS} for row in rows)
    return len(rows)
