from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

# ================================================================
# PEREZ AI — ELCID LIVE MARKET / NAV MONITOR
# READ ONLY — NO ORDERS — NO BROKER ACTION
# ================================================================

LTP = Decimal("109160")
SHARES = Decimal("200000")

# Audited FY2025-26 NAV anchors
ACCOUNTING_NAV_CR = Decimal("8673.45")
AUDITED_NET_INVESTMENT_CR = Decimal("9954.74")

# Current category-specific BASE realizable NAV
BASE_SOTP_NAV_CR = Decimal("7396.09")
BASE_VALUE_PER_SHARE = Decimal("369805")

# NSE identifiers
ELCID_SYMBOL = "ELCIDIN"
ASIAN_PAINTS_SYMBOL = "ASIANPAINT"


def rs(x):
    return f"₹{x.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"


def cr(x):
    return f"₹{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} Cr"


def pct(x):
    return f"{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}%"


def render_report():
    """Render the read-only monitor report; importing this module has no I/O."""
    market_cap = LTP * SHARES / Decimal("10000000")
    accounting_nav_per_share = ACCOUNTING_NAV_CR * Decimal("10000000") / SHARES
    market_vs_accounting_nav = (LTP / accounting_nav_per_share - Decimal("1")) * Decimal("100")
    market_vs_base_sotp = (LTP / BASE_VALUE_PER_SHARE - Decimal("1")) * Decimal("100")
    base_discount = (Decimal("1") - LTP / BASE_VALUE_PER_SHARE) * Decimal("100")

    print("=" * 82)
    print("PEREZ AI — ELCID LIVE MARKET / NAV MONITOR")
    print("=" * 82)
    print(f"Timestamp                   : {datetime.now().isoformat(timespec='seconds')}")
    print()
    print("MARKET")
    print("-" * 82)
    print(f"ELCID NSE Symbol            : {ELCID_SYMBOL}")
    print(f"Asian Paints NSE Symbol     : {ASIAN_PAINTS_SYMBOL}")
    print(f"ELCID LTP                   : {rs(LTP)}")
    print(f"Shares Outstanding          : {SHARES:,.0f}")
    print(f"Market Capitalization       : {cr(market_cap)}")
    print()
    print("AUDITED NAV ANCHORS")
    print("-" * 82)
    print(f"Accounting NAV              : {cr(ACCOUNTING_NAV_CR)}")
    print(f"Audited Net Investments     : {cr(AUDITED_NET_INVESTMENT_CR)}")
    print(f"Accounting NAV / Share      : {rs(accounting_nav_per_share)}")
    print()
    print("CATEGORY SOTP")
    print("-" * 82)
    print(f"Base realizable NAV         : {cr(BASE_SOTP_NAV_CR)}")
    print(f"Base modeled value / share  : {rs(BASE_VALUE_PER_SHARE)}")
    print()
    print("MARKET DISCOUNT")
    print("-" * 82)
    print(f"Market vs Accounting NAV    : {pct(market_vs_accounting_nav)}")
    print(f"Market vs Base SOTP         : {pct(market_vs_base_sotp)}")
    print(f"Discount to Base SOTP       : {pct(base_discount)}")
    print()
    print("SAFETY")
    print("-" * 82)
    print("STATUS                      : READ ONLY")
    print("ORDERS ENABLED              : FALSE")
    print("BROKER ACTION               : NONE")
    print("TRADING SIGNAL              : NONE")
    print("LIVE DATA CONNECTION        : NOT YET CONNECTED")
    print()
    print("NEXT LAYER")
    print("-" * 82)
    print("1. Connect live ELCIDIN quote")
    print("2. Connect live ASIANPAINT quote")
    print("3. Revalue quoted holdings")
    print("4. Recalculate live NAV")
    print("5. Track discount/premium history")
    print("6. Keep order execution completely isolated")
    print("=" * 82)


if __name__ == "__main__":
    render_report()
