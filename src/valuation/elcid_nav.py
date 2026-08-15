from decimal import Decimal

# ================================================================
# PEREZ AI — ELCID FY2025-26 AUDITED NAV ENGINE
# PAPER / ANALYSIS ONLY — NO BROKER ACTION
# ================================================================

SHARES_OUTSTANDING = Decimal("200000")
AUDITED_INVESTMENTS_CR = Decimal("9954.74")
CASH_AND_BANK_CR = Decimal("2.3192")
OTHER_ASSETS_CR = Decimal("39.6034")
DEFERRED_TAX_CR = Decimal("1325.4609")
OTHER_LIABILITIES_CR = Decimal("0.4242")
AIF_UNCALLED_CR = Decimal("46.0230")
GROUP_COMPANY_VALUE_CR = Decimal("8815.24")

HAIRCUT_SCENARIOS = (0, 10, 20, 30, 40, 50)


def calculate_base_nav():
    gross_assets = (
        AUDITED_INVESTMENTS_CR
        + CASH_AND_BANK_CR
        + OTHER_ASSETS_CR
    )

    liabilities = DEFERRED_TAX_CR + OTHER_LIABILITIES_CR

    return gross_assets - liabilities - AIF_UNCALLED_CR


def calculate_scenario(haircut_percent, market_price):
    base_nav = calculate_base_nav()

    haircut = Decimal(str(haircut_percent)) / Decimal("100")
    adjusted_nav = base_nav - (GROUP_COMPANY_VALUE_CR * haircut)

    nav_per_share = (
        adjusted_nav * Decimal("10000000")
        / SHARES_OUTSTANDING
    )

    market_cap_cr = (
        SHARES_OUTSTANDING
        * Decimal(str(market_price))
        / Decimal("10000000")
    )

    market_discount = (
        (Decimal("1") - Decimal(str(market_price)) / nav_per_share)
        * Decimal("100")
    )

    return {
        "haircut_percent": haircut_percent,
        "adjusted_nav_cr": adjusted_nav,
        "nav_per_share": nav_per_share,
        "market_cap_cr": market_cap_cr,
        "market_discount_percent": market_discount,
    }


def generate_report(market_price):
    base_nav = calculate_base_nav()

    print("=" * 92)
    print("PEREZ AI — ELCID FY2025-26 AUDITED NAV ENGINE")
    print("=" * 92)
    print(f"Audited Investments          : ₹{AUDITED_INVESTMENTS_CR:,.2f} Cr")
    print(f"Cash + Bank                  : ₹{CASH_AND_BANK_CR:,.4f} Cr")
    print(f"Other Assets                : ₹{OTHER_ASSETS_CR:,.4f} Cr")
    print(f"Deferred Tax Liability      : ₹{DEFERRED_TAX_CR:,.4f} Cr")
    print(f"Other Liabilities           : ₹{OTHER_LIABILITIES_CR:,.4f} Cr")
    print(f"AIF Uncalled Commitment     : ₹{AIF_UNCALLED_CR:,.4f} Cr")
    print("-" * 92)
    print(f"BASE CONSERVATIVE NAV       : ₹{base_nav:,.4f} Cr")
    print(f"Shares Outstanding          : {SHARES_OUTSTANDING:,.0f}")
    print(f"Market Price                : ₹{Decimal(str(market_price)):,.2f}")
    print()
    print("HAIRCUT     ADJUSTED NAV       NAV / SHARE       MARKET DISCOUNT")
    print("-" * 92)

    for haircut in HAIRCUT_SCENARIOS:
        r = calculate_scenario(haircut, market_price)

        print(
            f"{haircut:>3}%"
            f"{'':>11}"
            f"₹{r['adjusted_nav_cr']:>12,.4f} Cr"
            f"{'':>8}"
            f"₹{r['nav_per_share']:>12,.2f}"
            f"{'':>9}"
            f"{r['market_discount_percent']:>9.2f}%"
        )

    print("=" * 92)
    print("AUDIT STATUS : FY2025-26 figures loaded")
    print("DOUBLE-COUNTING PROTECTION : ENABLED BY CONSOLIDATED NAV BASE")
    print("BROKER/API ACTION : NONE")
    print("TRADING MODE : PAPER ONLY")
    print("=" * 92)


if __name__ == "__main__":
    generate_report("109160")
