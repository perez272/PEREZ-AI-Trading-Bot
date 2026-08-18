"""Read-only ELCID-style candidate refresh from audited input data."""
from pathlib import Path
import csv
from typing import Iterable

INPUT = Path("data/hidden_value_source.csv")
OUTPUT = Path("data/hidden_value_candidates.csv")
FIELDS = ["symbol","market_cap_cr","estimated_nav_cr","listed_investments_cr","cash_cr","debt_cr","promoter_holding_pct","free_float_pct","avg_daily_value_cr","corporate_action","regulatory_catalyst","special_auction","restructuring_event","revenue_growth_pct","profit_growth_pct"]


def build_candidates(rows: Iterable[dict]) -> list[dict]:
    result=[]
    for row in rows:
        try:
            symbol=str(row["symbol"]).strip().upper()
            shares=float(row["shares_outstanding"]); price=float(row["market_price"])
            nav=float(row["estimated_nav_cr"]); listed=float(row.get("listed_investments_cr",0) or 0)
            if not symbol or shares<=0 or price<0 or nav<=0 or listed<0: continue
            result.append({k: row.get(k,"") for k in FIELDS} | {"symbol":symbol,"market_cap_cr":shares*price/1e7,"estimated_nav_cr":nav,"listed_investments_cr":listed})
        except (KeyError,TypeError,ValueError):
            continue
    return result


def refresh(input_path: Path=INPUT, output_path: Path=OUTPUT) -> int:
    rows=[] if not input_path.exists() else list(csv.DictReader(input_path.open(newline="",encoding="utf-8")))
    candidates=build_candidates(rows)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(candidates)
    return len(candidates)

if __name__=="__main__":
    print(f"REFRESHED HIDDEN-VALUE CANDIDATES: {refresh()}")
