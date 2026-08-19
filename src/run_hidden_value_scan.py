"""Run the read-only hidden-value refresh and discovery pipeline."""
from src.hidden_value_data_pipeline import refresh
from src.high_conviction_discovery import discover


def run() -> tuple[int, int, int, int]:
    refreshed = refresh()
    passed, watchlist, rejected = discover()
    print("=" * 72)
    print("PEREZ AI — ELCID-STYLE HIDDEN VALUE SCAN")
    print("=" * 72)
    print("MODE              : READ ONLY")
    print("PAPER TRADING     : ENABLED")
    print("ORDERS ENABLED    : FALSE")
    print(f"CANDIDATES BUILT  : {refreshed}")
    print(f"ADMITTED          : {len(passed)}")
    print(f"WATCHLIST         : {len(watchlist)}")
    print(f"REJECTED          : {len(rejected)}")
    for result in passed:
        print(f"ADMITTED {result['symbol']} | SCORE {result['score']}/100 | NAV DISCOUNT {result['nav_discount_pct']}%")
    for result in watchlist:
        print(f"WATCHLIST {result['symbol']} | SCORE {result['score']}/100 | NAV DISCOUNT {result['nav_discount_pct']}% | TRADE ELIGIBLE FALSE")
    for result in rejected:
        print(f"REJECTED {result['symbol']} | {result['reason']}")
    return refreshed, len(passed), len(watchlist), len(rejected)


if __name__ == "__main__":
    run()
