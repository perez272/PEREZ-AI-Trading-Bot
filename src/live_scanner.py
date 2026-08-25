import os
import time
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect
from watchlist import WATCHLIST

load_dotenv()

obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))

session = obj.generateSession(
    os.getenv("ANGEL_CLIENT_ID"),
    os.getenv("ANGEL_PASSWORD"),
    pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
)

if not session.get("status"):
    print("Login Failed")
    raise SystemExit(1)

print("Connected to Angel One\n")

while True:
    print("=" * 70)

    for exchange, symbol, token in WATCHLIST:
        try:
            from src.market_data_router import MarketDataRouter
            router = MarketDataRouter(obj)
            data, source = router.get_option_quote(exchange, str(token))
            if data is None:
                data = {}

            if data["status"]:
                ltp = data["data"]["ltp"]
                print(f"{symbol:<22} {ltp}")
            else:
                print(f"{symbol:<22} ERROR")
        except Exception as e:
            print(f"{symbol:<22} {e}")

    time.sleep(5)
