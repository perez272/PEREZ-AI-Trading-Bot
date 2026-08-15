from decimal import Decimal
from .elcid_nav import calculate_base_nav, calculate_scenario, HAIRCUT_SCENARIOS


def print_elcid_valuation(market_price):
    market_price = Decimal(str(market_price))
    base_nav = calculate_base_nav()

    print()
    print("=" * 92)
    print("PEREZ AI — ELCID FY2025-26 REALIZABLE VALUE")
    print("=" * 92)
    print(f"Market Price                    : ₹{market_price:,.2f}")
    print(f"Base Conservative NAV           : ₹{base_nav:,.4f} Cr")
    print()
    print("HAIRCUT     ADJUSTED NAV       NAV / SHARE       MARKET DISCOUNT")
    print("-" * 92)

    for haircut in HAIRCUT_SCENARIOS:
        result = calculate_scenario(haircut, market_price)

        print(
            f"{haircut:>3}%"
            f"{'':>11}"
            f"₹{result['adjusted_nav_cr']:>12,.4f} Cr"
            f"{'':>8}"
            f"₹{result['nav_per_share']:>12,.2f}"
            f"{'':>9}"
            f"{result['market_discount_percent']:>9.2f}%"
        )

    print("-" * 92)
    print("ELCID VALUATION: ANALYSIS ONLY")
    print("BROKER/API ACTION: NONE")
    print("TRADING MODE: PAPER ONLY")
    print("=" * 92)


if __name__ == "__main__":
    print_elcid_valuation("109160")
