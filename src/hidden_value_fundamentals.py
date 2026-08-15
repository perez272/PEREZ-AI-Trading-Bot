from pathlib import Path
import csv
from src.hidden_value_detector import HiddenValueInput, calculate_hidden_value_score

OUT = Path("data/hidden_value_candidates.csv")

FIELDS = [
    "symbol","market_cap_cr","estimated_nav_cr","listed_investments_cr",
    "cash_cr","debt_cr","promoter_holding_pct","free_float_pct",
    "avg_daily_value_cr","corporate_action","regulatory_catalyst",
    "special_auction","restructuring_event","revenue_growth_pct",
    "profit_growth_pct"
]

def score_row(row):
    x = HiddenValueInput(
        symbol=row["symbol"],
        market_cap_cr=float(row.get("market_cap_cr", 0) or 0),
        estimated_nav_cr=float(row.get("estimated_nav_cr", 0) or 0),
        listed_investments_cr=float(row.get("listed_investments_cr", 0) or 0),
        cash_cr=float(row.get("cash_cr", 0) or 0),
        debt_cr=float(row.get("debt_cr", 0) or 0),
        promoter_holding_pct=float(row.get("promoter_holding_pct", 0) or 0),
        free_float_pct=float(row.get("free_float_pct", 100) or 100),
        avg_daily_value_cr=float(row.get("avg_daily_value_cr", 0) or 0),
        corporate_action=str(row.get("corporate_action","")).lower()=="true",
        regulatory_catalyst=str(row.get("regulatory_catalyst","")).lower()=="true",
        special_auction=str(row.get("special_auction","")).lower()=="true",
        restructuring_event=str(row.get("restructuring_event","")).lower()=="true",
        revenue_growth_pct=float(row.get("revenue_growth_pct", 0) or 0),
        profit_growth_pct=float(row.get("profit_growth_pct", 0) or 0),
    )
    return calculate_hidden_value_score(x)

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    if not OUT.exists():
        with OUT.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

    print("=" * 65)
    print("PEREZ AI — HIDDEN VALUE FUNDAMENTALS PIPELINE")
    print("=" * 65)
    print(f"Input file : {OUT}")
    print("Mode       : READ ONLY")
    print("Orders     : FALSE")
    print("Status     : READY FOR FUNDAMENTAL DATA")
    print("=" * 65)

if __name__ == "__main__":
    main()
