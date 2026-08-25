import os
import json
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect

load_dotenv()

obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))

session = obj.generateSession(
    os.getenv("ANGEL_CLIENT_ID"),
    os.getenv("ANGEL_PASSWORD"),
    pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
)

if not session.get("status"):
    print("Login Failed")
    exit()

with open("data/instruments.json") as f:
    instruments = json.load(f)

nifty = next(
    x for x in instruments
    if x.get("name") == "NIFTY"
    and x.get("symbol") == "Nifty 50"
    and x.get("exch_seg") == "NSE"
)

exchange = nifty["exch_seg"]
token = nifty["token"]
symbol = nifty["symbol"]

print(f"Fetching live price for {symbol}...")

from src.market_data_router import MarketDataRouter
router = MarketDataRouter(obj)
quote, source = router.get_option_quote(exchange, str(token))

print(quote)
