"""Read-only ELCID live category-SOTP NAV engine.

Importing this module is deliberately side-effect free. Angel One credentials,
sessions, and market-data requests are created only by ``get_live_nav()`` or
when this module is executed directly.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from dotenv import load_dotenv

from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient

load_dotenv()

ELCID = ("NSE", "ELCIDIN-EQ", "762658")
ASIAN_PAINTS = ("NSE", "ASIANPAINT-EQ", "236")

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
AUDITED_ASIAN_PAINTS_SHARES = Decimal("40615840")
AUDITED_ASIAN_PAINTS_VALUE_CR = Decimal("8794.1417")


def rs(x: Decimal) -> str:
    return f"₹{x.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"


def cr(x: Decimal) -> str:
    return f"₹{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} Cr"


def pct(x: Decimal) -> str:
    return f"{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}%"


@lru_cache(maxsize=1)
def _get_client() -> AngelClient:
    """Create the broker client only when live data is explicitly requested."""
    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")
    if not all([api_key, client_id, password, totp_secret]):
        raise RuntimeError("Missing Angel One credentials in .env")
    session = SessionManager(api_key, client_id, password, totp_secret)
    return AngelClient(session.get_client(), session_manager=session)


def live_ltp(instrument) -> Decimal:
    exchange, symbol, token = instrument
    response = _get_client().get_ltp(exchange, symbol, token)
    if not response:
        raise RuntimeError(f"No response for {symbol}")
    if isinstance(response, dict):
        if response.get("status") is False:
            raise RuntimeError(f"{symbol} API error: {response.get('message')}")
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("ltp", "LTP", "close"):
                if data.get(key) is not None:
                    return Decimal(str(data[key]))
    raise RuntimeError(f"Unable to extract LTP for {symbol}: {response}")


def get_live_nav() -> dict:
    """Fetch live prices and calculate the complete read-only NAV snapshot."""
    elcid_ltp = live_ltp(ELCID)
    asian_paints_ltp = live_ltp(ASIAN_PAINTS)
    audited_reference_price = AUDITED_ASIAN_PAINTS_VALUE_CR * Decimal("10000000") / AUDITED_ASIAN_PAINTS_SHARES
    asian_live_factor = asian_paints_ltp / audited_reference_price
    live_categories = dict(AUDITED_CATEGORIES)
    live_categories["Asian Paints"] = AUDITED_ASIAN_PAINTS_SHARES * asian_paints_ltp / Decimal("10000000")
    realizable = {
        category: value * (Decimal("1") - DISCOUNTS[category])
        for category, value in live_categories.items()
    }
    gross_realizable = sum(realizable.values())
    holding_reserve_amount = gross_realizable * HOLDING_RESERVE
    after_holding_reserve = gross_realizable - holding_reserve_amount
    tax_reserve_amount = after_holding_reserve * TAX_RESERVE
    live_sotp_nav_cr = after_holding_reserve - tax_reserve_amount
    live_value_per_share = live_sotp_nav_cr * Decimal("10000000") / SHARES
    market_cap_cr = elcid_ltp * SHARES / Decimal("10000000")
    discount_to_live_sotp = (Decimal("1") - elcid_ltp / live_value_per_share) * Decimal("100")
    market_vs_accounting = (
        elcid_ltp / (ACCOUNTING_NAV_CR * Decimal("10000000") / SHARES) - Decimal("1")
    ) * Decimal("100")
    return {
        "elcid_ltp": elcid_ltp,
        "asian_paints_ltp": asian_paints_ltp,
        "live_categories": live_categories,
        "realizable": realizable,
        "gross_realizable": gross_realizable,
        "holding_reserve_amount": holding_reserve_amount,
        "tax_reserve_amount": tax_reserve_amount,
        "live_sotp_nav_cr": live_sotp_nav_cr,
        "live_value_per_share": live_value_per_share,
        "market_cap_cr": market_cap_cr,
        "discount_to_live_sotp": discount_to_live_sotp,
        "market_vs_accounting": market_vs_accounting,
        "asian_live_factor": asian_live_factor,
    }


def main() -> None:
    nav = get_live_nav()
    print("=" * 82)
    print("PEREZ AI — ELCID LIVE CATEGORY-SOTP NAV ENGINE")
    print("=" * 82)
    print(f"Timestamp                   : {datetime.now().isoformat(timespec='seconds')}")
    print("MODE                        : READ ONLY")
    print("ORDERS ENABLED              : FALSE")
    print("BROKER ACTION               : NONE\n")
    print("LIVE MARKET")
    print("-" * 82)
    print(f"ELCIDIN LTP                 : {rs(nav['elcid_ltp'])}")
    print(f"ASIAN PAINTS LTP            : {rs(nav['asian_paints_ltp'])}")
    print(f"ELCID Market Cap            : {cr(nav['market_cap_cr'])}\n")
    print("AUDITED FY2025-26 ANCHORS")
    print("-" * 82)
    print(f"Accounting NAV               : {cr(ACCOUNTING_NAV_CR)}")
    print(f"Audited Net Investments      : {cr(AUDITED_NET_INVESTMENT_CR)}\n")
    print("LIVE CATEGORY REVALUATION")
    print("-" * 82)
    print(f"Asian Paints audited value  : {cr(AUDITED_CATEGORIES['Asian Paints'])}")
    print(f"Asian Paints live value     : {cr(nav['live_categories']['Asian Paints'])}")
    print(f"Asian Paints live factor    : {nav['asian_live_factor'].quantize(Decimal('0.0001'))}x\n")
    print("BASE REALIZABLE SOTP")
    print("-" * 82)
    for category, value in nav["live_categories"].items():
        print(f"{category:<28}: {cr(value):>18}  discount={pct(DISCOUNTS[category]):>8}  realizable={cr(nav['realizable'][category]):>18}")
    print("-" * 82)
    print(f"Gross realizable value      : {cr(nav['gross_realizable'])}")
    print(f"Holding-company reserve     : {cr(nav['holding_reserve_amount'])}")
    print(f"Tax reserve                 : {cr(nav['tax_reserve_amount'])}")
    print(f"LIVE SOTP NAV               : {cr(nav['live_sotp_nav_cr'])}\n")
    print("LIVE VALUE")
    print("-" * 82)
    print(f"Live SOTP value / share     : {rs(nav['live_value_per_share'])}")
    print(f"Current ELCID LTP           : {rs(nav['elcid_ltp'])}")
    print(f"Discount to live SOTP       : {pct(nav['discount_to_live_sotp'])}")
    print(f"Market vs accounting NAV    : {pct(nav['market_vs_accounting'])}\n")
    print("SAFETY")
    print("-" * 82)
    print("ORDER API                  : NOT CALLED")
    print("POSITION API               : NOT CALLED")
    print("TRADE SIGNAL               : NONE")
    print("ORDERS ENABLED             : FALSE")
    print("STATUS                     : READ-ONLY LIVE NAV")
    print("=" * 82)


if __name__ == "__main__":
    main()
