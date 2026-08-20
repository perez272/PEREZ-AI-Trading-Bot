"""Compatibility facade for the PRO multi-timeframe market scanner."""

from src.mtf_scanner import scan_market_pro


def scan_market():
    return scan_market_pro()


def select_best_candidate(results, minimum_score=65):
    eligible = [
        item for item in results
        if item.get("data_quality")
        and item.get("score", 0) >= minimum_score
        and item.get("signal") in ("BUY CE", "BUY PE")
    ]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nPEREZ PRO AI — MULTI-TIMEFRAME OPPORTUNITY RANKING")
    print("-" * 120)
    for rank, item in enumerate(results, 1):
        scores = item.get("timeframe_scores", {})
        dirs = item.get("timeframe_directions", {})
        print(
            f"#{rank:<2} {item['symbol']:<12} Score={item['score']:>5.1f} "
            f"Signal={item['signal']:<8} "
            f"5m/15m/60m={scores.get('5m', 0):.1f}/{scores.get('15m', 0):.1f}/{scores.get('60m', 0):.1f} "
            f"Dirs={dirs} Regime={item.get('trend', ''):<18} "
            f"Structure={item.get('structure', ''):<18} Vol={item.get('volume_ratio', 0):.2f}x"
        )
    print("-" * 120)


if __name__ == "__main__":
    print_results(scan_market())
