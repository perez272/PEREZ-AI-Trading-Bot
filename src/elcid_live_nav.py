import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from dotenv import load_dotenv

from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient

load_dotenv()

# ================================================================
# PEREZ AI — ELCID LIVE CATEGORY-SOTP NAV ENGINE
# READ ONLY — NO ORDERS — NO POSITION ACTION
# ================================================================

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    raise RuntimeError("Missing Angel One credentials in .env")

# ------------------------------------------------
# VERIFIED INSTRUMENT MASTER TOKENS
# ------------------------------------------------

ELCID = ("NSE", "ELCIDIN-EQ", "762658")
ASIAN_PAINTS = ("NSE", "ASIANPAINT-EQ", "236")

# ------------------------------------------------
# AUDITED FY2025-26 CATEGORY VALUES
# ₹ crore
# ------------------------------------------------

AUDITED_CATEGORIES = {
    "Asian Paints": Decimal("8794.14"),
    "Other quoted equity": Decimal("118.58"),
    "Unquoted equity": Decimal("78.84"),
    "CCPS": Decimal("40.51"),
    "Mutual funds": Decimal("757.52"),
    "Government securities": Decimal("0.49"),
    "Corporate bonds": Decimal("10.29"),
    "AIF": Decimal("154.36"),
}

AUDITED_NET_INVESTMENT_CR = Decimal("9954.74")
ACCOUNTING_NAV_CR = Decimal("8673.45")
SHARES = Decimal("200000")

# ------------------------------------------------
# BASE REALIZATION DISCOUNTS
# ------------------------------------------------

DISCOUNTS = {
    "Asian Paints": Decimal("0.10"),
    "Other quoted equity": Decimal("0.12"),
    "Unquoted equity": Decimal("0.30"),
    "CCPS": Decimal("0.35"),
    "Mutual funds": Decimal("0.05"),
    "Government securities": Decimal("0.03"),
    "Corporate bonds": Decimal("0.10"),
    "AIF": Decimal("0.25"),
}

HOLDING_RESERVE = Decimal("0.03")
TAX_RESERVE = Decimal("0.00")

# ------------------------------------------------
# HELPERS
# ------------------------------------------------

def rs(x):
    return f"₹{x.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"

def cr(x):
    return f"₹{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} Cr"

def pct(x):
    return f"{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}%"

# ------------------------------------------------
# LIVE QUOTE
# ------------------------------------------------

session_manager = SessionManager(
    API_KEY,
    CLIENT_ID,
    PASSWORD,
    TOTP_SECRET,
)

smartapi = session_manager.get_client()

client = AngelClient(
    smartapi,
    session_manager=session_manager,
)

def live_ltp(instrument):
    exchange, symbol, token = instrument

    response = client.get_ltp(
        exchange,
        symbol,
        token,
    )

    if not response:
        raise RuntimeError(f"No response for {symbol}")

    if isinstance(response, dict):
        if response.get("status") is False:
            raise RuntimeError(
                f"{symbol} API error: {response.get('message')}"
            )

        data = response.get("data")

        if isinstance(data, dict):
            for key in ("ltp", "LTP", "close"):
                if data.get(key) is not None:
                    return Decimal(str(data[key]))

    raise RuntimeError(
        f"Unable to extract LTP for {symbol}: {response}"
    )

elcid_ltp = live_ltp(ELCID)
asian_paints_ltp = live_ltp(ASIAN_PAINTS)

# ------------------------------------------------
# LIVE ASIAN PAINTS REVALUATION
#
# The audited Asian Paints category is the
# investment value already recorded in FY2025-26.
#
# We adjust it by the live market-price movement
# relative to the audited reference price.
#
# The audited reference price is intentionally
# kept explicit rather than hidden.
# ------------------------------------------------

AUDITED_ASIAN_PAINTS_SHARES = Decimal("40615840")
AUDITED_ASIAN_PAINTS_VALUE_CR = Decimal("8794.1417")

# Audited FY2025-26 holding:
# 4,06,15,840 Asian Paints shares
# carrying value ₹8,79,414.17 lakhs = ₹8,794.1417 Cr
#
# Live value is now calculated directly from the audited
# holding quantity multiplied by the live Asian Paints LTP.

audited_reference_price = (
    AUDITED_ASIAN_PAINTS_VALUE_CR *
    Decimal("10000000") /
    AUDITED_ASIAN_PAINTS_SHARES
)

asian_live_factor = (
    asian_paints_ltp /
    audited_reference_price
)

live_categories = dict(AUDITED_CATEGORIES)

live_categories["Asian Paints"] = (
    AUDITED_ASIAN_PAINTS_SHARES *
    asian_paints_ltp /
    Decimal("10000000")
)

# ------------------------------------------------
# CATEGORY REALIZATION
# ------------------------------------------------

realizable = {}

for category, value in live_categories.items():
    discount = DISCOUNTS[category]
    realizable[category] = value * (Decimal("1") - discount)

gross_realizable = sum(realizable.values())

holding_reserve_amount = (
    gross_realizable * HOLDING_RESERVE
)

after_holding_reserve = (
    gross_realizable -
    holding_reserve_amount
)

tax_reserve_amount = (
    after_holding_reserve * TAX_RESERVE
)

live_sotp_nav_cr = (
    after_holding_reserve -
    tax_reserve_amount
)

live_value_per_share = (
    live_sotp_nav_cr *
    Decimal("10000000") /
    SHARES
)

market_cap_cr = (
    elcid_ltp *
    SHARES /
    Decimal("10000000")
)

discount_to_live_sotp = (
    (Decimal("1") -
     elcid_ltp / live_value_per_share)
    * Decimal("100")
)

market_vs_accounting = (
    (elcid_ltp /
     (ACCOUNTING_NAV_CR *
      Decimal("10000000") /
      SHARES)
     - Decimal("1"))
    * Decimal("100")
)

# ------------------------------------------------
# OUTPUT
# ------------------------------------------------

print("=" * 82)
print("PEREZ AI — ELCID LIVE CATEGORY-SOTP NAV ENGINE")
print("=" * 82)
print(f"Timestamp                   : {datetime.now().isoformat(timespec='seconds')}")
print("MODE                        : READ ONLY")
print("ORDERS ENABLED              : FALSE")
print("BROKER ACTION               : NONE")
print()

print("LIVE MARKET")
print("-" * 82)
print(f"ELCIDIN LTP                 : {rs(elcid_ltp)}")
print(f"ASIAN PAINTS LTP            : {rs(asian_paints_ltp)}")
print(f"ELCID Market Cap            : {cr(market_cap_cr)}")
print()

print("AUDITED FY2025-26 ANCHORS")
print("-" * 82)
print(f"Accounting NAV               : {cr(ACCOUNTING_NAV_CR)}")
print(f"Audited Net Investments      : {cr(AUDITED_NET_INVESTMENT_CR)}")
print()

print("LIVE CATEGORY REVALUATION")
print("-" * 82)
print(
    f"Asian Paints audited value  : "
    f"{cr(AUDITED_CATEGORIES['Asian Paints'])}"
)
print(
    f"Asian Paints live value     : "
    f"{cr(live_categories['Asian Paints'])}"
)
print(
    f"Asian Paints live factor    : "
    f"{asian_live_factor.quantize(Decimal('0.0001'))}x"
)
print()

print("BASE REALIZABLE SOTP")
print("-" * 82)

for category in live_categories:
    print(
        f"{category:<28}: "
        f"{cr(live_categories[category]):>18}  "
        f"discount={pct(DISCOUNTS[category]):>8}  "
        f"realizable={cr(realizable[category]):>18}"
    )

print("-" * 82)
print(f"Gross realizable value      : {cr(gross_realizable)}")
print(f"Holding-company reserve     : {cr(holding_reserve_amount)}")
print(f"Tax reserve                 : {cr(tax_reserve_amount)}")
print(f"LIVE SOTP NAV               : {cr(live_sotp_nav_cr)}")
print()

print("LIVE VALUE")
print("-" * 82)
print(f"Live SOTP value / share     : {rs(live_value_per_share)}")
print(f"Current ELCID LTP           : {rs(elcid_ltp)}")
print(f"Discount to live SOTP       : {pct(discount_to_live_sotp)}")
print(f"Market vs accounting NAV    : {pct(market_vs_accounting)}")
print()

print("SAFETY")
print("-" * 82)
print("ORDER API                  : NOT CALLED")
print("POSITION API               : NOT CALLED")
print("TRADE SIGNAL               : NONE")
print("ORDERS ENABLED             : FALSE")
print("STATUS                     : READ-ONLY LIVE NAV")
print("=" * 82)
