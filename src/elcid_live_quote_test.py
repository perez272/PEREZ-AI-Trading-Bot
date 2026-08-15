import os
from decimal import Decimal
from dotenv import load_dotenv

from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient

load_dotenv()

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    raise RuntimeError("Missing Angel One credentials in .env")

ELCID = {
    "exchange": "NSE",
    "symbol": "ELCIDIN-EQ",
    "token": "762658",
}

ASIAN_PAINTS = {
    "exchange": "NSE",
    "symbol": "ASIANPAINT-EQ",
    "token": "236",
}

print("=" * 82)
print("PEREZ AI — ELCID LIVE QUOTE CONNECTIVITY TEST")
print("=" * 82)
print("MODE                 : READ ONLY")
print("ORDERS ENABLED       : FALSE")
print("BROKER ACTION        : NONE")
print()

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

def get_price(instrument):
    response = client.get_ltp(
        instrument["exchange"],
        instrument["symbol"],
        instrument["token"],
    )

    if not response:
        raise RuntimeError(
            f"No response received for {instrument['symbol']}"
        )

    if isinstance(response, dict):
        if response.get("status") is False:
            raise RuntimeError(
                f"API rejected {instrument['symbol']}: "
                f"{response.get('message')}"
            )

        data = response.get("data")

        if isinstance(data, dict):
            for key in ("ltp", "LTP", "close"):
                if data.get(key) is not None:
                    return Decimal(str(data[key])), response

        if data is not None:
            print("RAW DATA:", data)

    raise RuntimeError(
        f"Could not extract LTP for {instrument['symbol']}: {response}"
    )

print("===== ELCIDIN =====")
elcid_price, elcid_response = get_price(ELCID)
print(f"Symbol               : {ELCID['symbol']}")
print(f"Token                : {ELCID['token']}")
print(f"Live LTP             : ₹{elcid_price:,.2f}")
print()

print("===== ASIAN PAINTS =====")
asian_price, asian_response = get_price(ASIAN_PAINTS)
print(f"Symbol               : {ASIAN_PAINTS['symbol']}")
print(f"Token                : {ASIAN_PAINTS['token']}")
print(f"Live LTP             : ₹{asian_price:,.2f}")
print()

print("=" * 82)
print("CONNECTIVITY RESULT")
print("=" * 82)
print("ELCIDIN LIVE QUOTE   : PASS")
print("ASIANPAINT LIVE QUOTE: PASS")
print("ORDER API CALLED     : FALSE")
print("POSITION API CALLED  : FALSE")
print("TRADE SIGNAL         : NONE")
print("STATUS               : READ-ONLY LIVE DATA CONNECTED")
print("=" * 82)
