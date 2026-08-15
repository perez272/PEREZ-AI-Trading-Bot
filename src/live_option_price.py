import time
from datetime import datetime, timedelta
from src.market_scanner_v3 import get_client

_price_cache = {}

def get_option_ltp(exchange, symbol, token):
    key = (exchange, symbol, str(token))
    now = datetime.now()

    cached = _price_cache.get(key)
    if cached and (now - cached[1]) < timedelta(seconds=5):
        return cached[0]

    try:
        response = get_client().get_ltp(exchange, symbol, token)

        if response and response.get("status") and response.get("data"):
            price = float(response["data"]["ltp"])
            _price_cache[key] = (price, now)
            return price

    except Exception as e:
        print("LTP ERROR:", e)
        time.sleep(2)

    return cached[0] if cached else None
