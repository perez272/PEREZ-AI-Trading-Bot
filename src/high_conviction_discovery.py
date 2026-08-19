"""PEREZ AI — strict, read-only fundamental admission layer.

Discovery consumes normalized ranking output when available. It never
converts a valuation discount into a catalyst and never enables live orders.
"""
from pathlib import Path
import csv
from src.high_conviction_gate import evaluate
from src.catalyst_engine import verify_catalyst

CANDIDATE_FILE = Path("data/hidden_value_candidates.csv")
RANKED_FILE = Path("data/hidden_value_ranked.csv")
REQUIRED = {
    "symbol", "market_cap_cr", "estimated_nav_cr", "listed_investments_cr",
    "corporate_action", "regulatory_catalyst", "special_auction",
    "restructuring_event"
}


def truthy(v):
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}


def _load_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _normalized_row(row):
    """Fill discovery inputs from normalized ranking fields when available."""
    out = dict(row)
    if not out.get("market_cap_cr"):
        try:
            out["market_cap_cr"] = float(out.get("shares_outstanding") or 0) * float(out.get("market_price") or 0) / 1e7
        except (TypeError, ValueError):
            pass
    return out


def discover(path=CANDIDATE_FILE):
    passed, rejected = [], []
    source_rows = _load_rows(Path(path))
    if not source_rows:
        return [], [{"symbol": "*", "reason": "CANDIDATE_FILE_MISSING"}]

    ranked = {str(r.get("symbol") or "").strip().upper(): r for r in _load_rows(RANKED_FILE)}

    for raw in source_rows:
        symbol = (raw.get("symbol") or "").strip().upper()
        row = _normalized_row({**raw, **ranked.get(symbol, {})})

        if not symbol:
            rejected.append({"symbol": "*", "reason": "MISSING_SYMBOL"})
            continue
        if not REQUIRED.issubset(row):
            rejected.append({"symbol": symbol, "reason": "MISSING_REQUIRED_FIELDS"})
            continue

        try:
            market_cap = float(row.get("market_cap_cr") or 0)
            nav = float(row.get("estimated_nav_cr") or 0)
            listed = float(row.get("listed_investments_cr") or 0)
            if market_cap <= 0 or nav <= 0:
                rejected.append({"symbol": symbol, "reason": "MISSING_NAV_OR_MARKET_CAP"})
                continue
            if listed <= 0:
                rejected.append({"symbol": symbol, "reason": "INSUFFICIENT_ASSET_COVERAGE"})
                continue
        except (TypeError, ValueError):
            rejected.append({"symbol": symbol, "reason": "INVALID_FUNDAMENTAL_VALUE"})
            continue

        catalyst_check = verify_catalyst(row)
        if not catalyst_check["verified"]:
            rejected.append({
                "symbol": symbol,
                "reason": catalyst_check["reason"],
                "nav_discount_pct": row.get("nav_discount_pct", ""),
                "classification": row.get("classification", ""),
                "catalyst_types": catalyst_check.get("types", []),
            })
            continue

        try:
            clean = {
                "symbol": symbol,
                "market_cap_cr": market_cap,
                "estimated_nav_cr": nav,
                "listed_investments_cr": listed,
                "cash_cr": float(row.get("cash_cr") or 0),
                "debt_cr": float(row.get("debt_cr") or 0),
                "promoter_holding_pct": float(row.get("promoter_holding_pct") or 0),
                "free_float_pct": float(row.get("free_float_pct") or 0),
                "avg_daily_value_cr": float(row.get("avg_daily_value_cr") or 0),
                "corporate_action": truthy(row.get("corporate_action")),
                "regulatory_catalyst": truthy(row.get("regulatory_catalyst")),
                "special_auction": truthy(row.get("special_auction")),
                "restructuring_event": truthy(row.get("restructuring_event")),
                "revenue_growth_pct": float(row.get("revenue_growth_pct") or 0),
                "profit_growth_pct": float(row.get("profit_growth_pct") or 0),
            }
            result = evaluate(clean)
            result["catalyst_verified"] = True
            result["catalyst_types"] = catalyst_check["types"]
            result["catalyst_source"] = catalyst_check["source_url"]
            result["catalyst_as_of_date"] = catalyst_check["as_of_date"]
        except (TypeError, ValueError, KeyError) as e:
            rejected.append({"symbol": symbol, "reason": f"INVALID_INPUT:{type(e).__name__}:{e}"})
            continue

        if result["HIGH_CONVICTION"] and result["ORDERS_ENABLED"] is False:
            passed.append(result)
        else:
            rejected.append({
                "symbol": symbol,
                "reason": "STRICT_GATE_REJECT",
                "score": result["score"]
            })

    return sorted(passed, key=lambda x: x["score"], reverse=True), rejected


if __name__ == "__main__":
    passed, rejected = discover()
    print("=" * 72)
    print("PEREZ AI — HIGH-CONVICTION FUNDAMENTAL DISCOVERY")
    print("=" * 72)
    print("MODE              : READ ONLY")
    print("PAPER TRADING     : ENABLED")
    print("LIVE ORDERS       : DISABLED")
    print(f"ADMITTED          : {len(passed)}")
    print(f"REJECTED          : {len(rejected)}")
    print("-" * 72)
    for x in passed:
        print(f"ADMITTED {x['symbol']} | SCORE {x['score']}/100 | NAV DISCOUNT {x['nav_discount_pct']}% | ASSET RATIO {x['asset_ratio']}x")
    for x in rejected:
        print(f"REJECTED {x['symbol']} | {x['reason']}")
    print("-" * 72)
    print("ORDERS ENABLED     : FALSE")
