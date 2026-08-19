"""Read-only normalized ranking for ELCID-style hidden-value candidates.

This module ranks valuation dislocations without inventing catalysts. Screening
NAVs are explicitly labeled as book-value based; ELCID can carry the verified
live SOTP source metadata already present in the candidate file.
"""
from __future__ import annotations

import csv
from pathlib import Path

INPUT = Path("data/hidden_value_candidates.csv")
OUTPUT = Path("data/hidden_value_ranked.csv")


def _num(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def rank_rows(rows: list[dict]) -> list[dict]:
    ranked = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        shares = _num(row, "shares_outstanding")
        price = _num(row, "market_price")
        nav_cr = _num(row, "estimated_nav_cr")

        if not symbol or shares <= 0 or price <= 0 or nav_cr <= 0:
            continue

        nav_per_share = nav_cr * 1e7 / shares
        discount_pct = max(0.0, (1.0 - price / nav_per_share) * 100.0) if nav_per_share > 0 else 0.0
        premium_pct = max(0.0, (price / nav_per_share - 1.0) * 100.0) if nav_per_share > 0 else 0.0
        nav_multiple = price / nav_per_share if nav_per_share > 0 else 0.0

        if discount_pct >= 80:
            classification = "DEEP_VALUE_WATCHLIST"
        elif discount_pct >= 50:
            classification = "VALUE_WATCHLIST"
        elif discount_pct >= 25:
            classification = "MODERATE_DISCOUNT"
        else:
            classification = "LOW_DISCOUNT_OR_PREMIUM"

        catalyst = any(
            str(row.get(k) or "").strip().lower() in {"1", "true", "yes", "y"}
            for k in ("corporate_action", "regulatory_catalyst", "special_auction", "restructuring_event")
        )
        source_name = str(row.get("source_name") or "")
        nav_type = (
            "VERIFIED_LIVE_SOTP"
            if symbol == "ELCIDINVESTMENTS" and "verified live elcid" in source_name.lower()
            else "BOOK_VALUE_SCREENING"
        )

        # Ranking is valuation-only. Catalyst is a separate gate and is never inferred.
        score = min(
            100.0,
            round(discount_pct * 0.75 + (15.0 if nav_type == "VERIFIED_LIVE_SOTP" else 0.0) + (10.0 if catalyst else 0.0), 2),
        )
        ranked.append({
            **row,
            "nav_per_share": round(nav_per_share, 2),
            "nav_multiple": round(nav_multiple, 4),
            "nav_discount_pct": round(discount_pct, 2),
            "nav_premium_pct": round(premium_pct, 2),
            "valuation_score": score,
            "classification": classification,
            "catalyst_verified": catalyst,
            "nav_type": nav_type,
            "orders_enabled": "FALSE",
        })

    return sorted(ranked, key=lambda x: (x["valuation_score"], x["nav_discount_pct"]), reverse=True)


def refresh(input_path: Path = INPUT, output_path: Path = OUTPUT) -> int:
    if not input_path.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return 0
    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ranked = rank_rows(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(ranked[0].keys()) if ranked else []
    if not fields:
        with input_path.open(newline="", encoding="utf-8") as f:
            fields = list(csv.DictReader(f).fieldnames or [])
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ranked)
    return len(ranked)


if __name__ == "__main__":
    count = refresh()
    print(f"RANKED HIDDEN-VALUE CANDIDATES: {count}")
    print("READ ONLY: TRUE")
    print("ORDERS ENABLED: FALSE")
