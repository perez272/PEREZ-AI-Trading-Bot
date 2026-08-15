"""PEREZ AI — strict, read-only fundamental admission layer."""
from pathlib import Path
import csv
from src.high_conviction_gate import evaluate

CANDIDATE_FILE = Path("data/hidden_value_candidates.csv")
REQUIRED = {
    "symbol","market_cap_cr","estimated_nav_cr","listed_investments_cr",
    "corporate_action","regulatory_catalyst","special_auction",
    "restructuring_event"
}

def truthy(v):
    return str(v or "").strip().lower() in {"1","true","yes","y"}

def discover(path=CANDIDATE_FILE):
    passed, rejected = [], []

    if not Path(path).exists():
        return [], [{"symbol":"*","reason":"CANDIDATE_FILE_MISSING"}]

    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            symbol=(row.get("symbol") or "").strip().upper()

            if not symbol:
                rejected.append({"symbol":"*","reason":"MISSING_SYMBOL"})
                continue

            if not REQUIRED.issubset(row):
                rejected.append({"symbol":symbol,"reason":"MISSING_REQUIRED_FIELDS"})
                continue

            try:
                if any(float(row.get(k) or 0) <= 0 for k in (
                    "market_cap_cr","estimated_nav_cr","listed_investments_cr"
                )):
                    rejected.append({"symbol":symbol,"reason":"MISSING_NAV_OR_ASSETS"})
                    continue
            except ValueError:
                rejected.append({"symbol":symbol,"reason":"INVALID_FUNDAMENTAL_VALUE"})
                continue

            catalyst=any(truthy(row.get(k)) for k in (
                "corporate_action","regulatory_catalyst",
                "special_auction","restructuring_event"
            ))

            if not catalyst:
                rejected.append({"symbol":symbol,"reason":"MISSING_CATALYST"})
                continue

            try:
                clean = {
                    "symbol": symbol,
                    "market_cap_cr": float(row.get("market_cap_cr") or 0),
                    "estimated_nav_cr": float(row.get("estimated_nav_cr") or 0),
                    "listed_investments_cr": float(row.get("listed_investments_cr") or 0),
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
                result=evaluate(clean)
            except (TypeError,ValueError,KeyError) as e:
                rejected.append({
                    "symbol":symbol,
                    "reason":f"INVALID_INPUT:{type(e).__name__}:{e}"
                })
                continue

            if result["HIGH_CONVICTION"] and result["ORDERS_ENABLED"] is False:
                passed.append(result)
            else:
                rejected.append({
                    "symbol":symbol,
                    "reason":"STRICT_GATE_REJECT",
                    "score":result["score"]
                })

    return sorted(passed,key=lambda x:x["score"],reverse=True),rejected

if __name__=="__main__":
    passed,rejected=discover()

    print("="*72)
    print("PEREZ AI — HIGH-CONVICTION FUNDAMENTAL DISCOVERY")
    print("="*72)
    print("MODE              : READ ONLY")
    print("PAPER TRADING     : ENABLED")
    print("LIVE ORDERS       : DISABLED")
    print(f"ADMITTED          : {len(passed)}")
    print(f"REJECTED          : {len(rejected)}")
    print("-"*72)

    for x in passed:
        print(
            f"ADMITTED {x['symbol']} | "
            f"SCORE {x['score']}/100 | "
            f"NAV DISCOUNT {x['nav_discount_pct']}% | "
            f"ASSET RATIO {x['asset_ratio']}x"
        )

    for x in rejected:
        print(f"REJECTED {x['symbol']} | {x['reason']}")

    print("-"*72)
    print("ORDERS ENABLED     : FALSE")
