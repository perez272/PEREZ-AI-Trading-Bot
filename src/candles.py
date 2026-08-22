"""Optional candle-data utility.

Importing this module must never authenticate with Angel One or perform network I/O.
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv


def fetch_nifty_candles(days=5, interval="FIVE_MINUTE"):
    """Fetch NIFTY candles explicitly when called by a runtime utility."""
    from SmartApi import SmartConnect
    import pyotp

    load_dotenv()
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    session = obj.generateSession(
        os.getenv("ANGEL_CLIENT_ID"),
        os.getenv("ANGEL_PASSWORD"),
        pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now(),
    )
    if not session or not session.get("status"):
        raise RuntimeError("Angel One login failed")

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    params = {
        "exchange": "NSE",
        "symboltoken": "99926000",
        "interval": interval,
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }
    return obj.getCandleData(params)


if __name__ == "__main__":
    print(fetch_nifty_candles())
