"""Read-only ELCID-style candidate refresh with auditable source metadata."""
from datetime import date, datetime
from pathlib import Path
import csv
from typing import Iterable

INPUT = Path("data/hidden_value_source.csv")
OUTPUT = Path("data/hidden_value_candidates.csv")
FIELDS = [
    "symbol", "shares_outstanding", "market_price", "estimated_nav_cr",
    "listed_investments_cr", "cash_cr", "debt_cr", "deferred_tax_cr",
    "uncalled_commitment_cr", "other_liabilities_cr", "promoter_holding_pct",
    "free_float_pct", "avg_daily_value_cr", "corporate_action",
    "regulatory_catalyst", "special_auction", "restructuring_event",
    "revenue_growth_pct", "profit_growth_pct", "source_url", "source_name",
    "as_of_date",
]

REQUIRED_SOURCE_FIELDS = ("source_url", "source_name", "as_of_date")


def _fresh_enough(value: str, max_age_days: int = 400) -> bool:
    try:
        d = date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return False
    return 0 <= (date.today() - d).days <= max_age_days


def build_candidates(rows: Iterable[dict], max_age_days: int = 400) -> list[dict]:
    result = []
    for row in rows:
        try:
            symbol = str(row["symbol"]).strip().upper()
            shares = float(row["shares_outstanding"])
            price = float(row["market_price"])
            nav = float(row["estimated_nav_cr"])
            listed = float(row.get("listed_investments_cr", 0) or 0)
            if not symbol or shares <= 0 or price < 0 or nav <= 0 or listed < 0:
                continue
            if any(not str(row.get(k, "")).strip() for k in REQUIRED_SOURCE_FIELDS):
                continue
            if not _fresh_enough(row["as_of_date"], max_age_days):
                continue

            clean = {k: row.get(k, "") for k in FIELDS}
            clean.update({
                "symbol": symbol,
                "shares_outstanding": shares,
                "market_price": price,
                "market_cap_cr": shares * price / 1e7,
                "estimated_nav_cr": nav,
                "listed_investments_cr": listed,
            })
            result.append(clean)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def refresh(input_path: Path = INPUT, output_path: Path = OUTPUT, max_age_days: int = 400) -> int:
    rows = []
    if input_path.exists():
        with input_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    candidates = build_candidates(rows, max_age_days=max_age_days)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS + ["market_cap_cr"])
        writer.writeheader()
        writer.writerows(candidates)
    return len(candidates)


if __name__ == "__main__":
    started = datetime.now().isoformat(timespec="seconds")
    count = refresh()
    print(f"REFRESHED HIDDEN-VALUE CANDIDATES: {count}")
    print(f"RUN TIME: {started}")
    print("READ ONLY: TRUE")
    print("ORDERS ENABLED: FALSE")
