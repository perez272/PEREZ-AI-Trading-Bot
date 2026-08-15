from src.hidden_value_detector import HiddenValueInput, calculate_hidden_value_score

def scan(candidates):
    results = []
    for data in candidates:
        result = calculate_hidden_value_score(HiddenValueInput(**data))
        results.append(result)
    return sorted(results, key=lambda x: x["score"], reverse=True)

if __name__ == "__main__":
    print("PEREZ AI — HIDDEN VALUE SCANNER")
    print("SAFE MODE: NO ORDERS")

    candidates = [
        {
            "symbol": "ELCIDINVESTMENTS",
            "market_cap_cr": 300,
            "estimated_nav_cr": 8000,
            "listed_investments_cr": 7000,
            "promoter_holding_pct": 74,
            "free_float_pct": 26,
            "avg_daily_value_cr": 0.01,
            "corporate_action": True,
            "regulatory_catalyst": True,
            "special_auction": True,
        }
    ]

    for r in scan(candidates):
        print(f"{r['symbol']:20} {r['score']:3}/100  {r['classification']}")
