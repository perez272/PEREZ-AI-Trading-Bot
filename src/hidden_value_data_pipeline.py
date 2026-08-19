"""Read-only hidden-value candidate refresh with auditable source metadata.

This module is the canonical producer for ``data/hidden_value_candidates.csv``.
It deliberately writes candidates atomically so an interrupted refresh cannot
leave discovery with a header-only/partially-written file.
"""
from datetime import date, datetime
from pathlib import Path
import csv
import os
import tempfile
from typing import Iterable

from src.hidden_value_ranking import rank_rows

INPUT = Path("data/hidden_value_source.csv")
OUTPUT = Path("data/hidden_value_candidates.csv")
RANKED_OUTPUT = Path("data/hidden_value_ranked.csv")
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
            if not symbol or shares <= 0 or price <= 0 or nav <= 0 or listed < 0:
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
                "market_cap_cr": round(shares * price / 1e7, 4),
                "estimated_nav_cr": nav,
                "listed_investments_cr": listed,
            })
            result.append(clean)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Replace a CSV atomically, preventing header-only files on interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def refresh(input_path: Path = INPUT, output_path: Path = OUTPUT, max_age_days: int = 400) -> int:
    rows = []
    if input_path.exists():
        with input_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    candidates = build_candidates(rows, max_age_days=max_age_days)
    candidate_fields = FIELDS + ["market_cap_cr"]
    _atomic_write_csv(output_path, candidate_fields, candidates)

    ranked = rank_rows(candidates)
    ranked_fields = list(ranked[0].keys()) if ranked else candidate_fields
    _atomic_write_csv(RANKED_OUTPUT, ranked_fields, ranked)

    # This invariant makes the pipeline self-auditing: ranking must never
    # silently contain a different candidate universe than the canonical file.
    if len(ranked) != len(candidates):
        raise RuntimeError(
            f"HIDDEN_VALUE_PIPELINE_INVARIANT_FAILED: candidates={len(candidates)} ranked={len(ranked)}"
        )
    return len(candidates)


if __name__ == "__main__":
    started = datetime.now().isoformat(timespec="seconds")
    count = refresh()
    ranked_count = sum(1 for _ in csv.DictReader(RANKED_OUTPUT.open(newline="", encoding="utf-8"))) if RANKED_OUTPUT.exists() else 0
    print(f"REFRESHED HIDDEN-VALUE CANDIDATES: {count}")
    print(f"RANKED HIDDEN-VALUE CANDIDATES: {ranked_count}")
    print(f"RUN TIME: {started}")
    print("READ ONLY: TRUE")
    print("ORDERS ENABLED: FALSE")
