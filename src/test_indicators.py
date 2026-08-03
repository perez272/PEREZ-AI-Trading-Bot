import os
import pyotp
from datetime import datetime, timedelta
from dotenv import load_dotenv
from SmartApi import SmartConnect

from indicators import calculate_indicators

load_dotenv()

obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))

obj.generateSession(
    os.getenv("ANGEL_CLIENT_ID"),
    os.getenv("ANGEL_PASSWORD"),
    pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
)

to_date = datetime.now()
from_date = to_date - timedelta(days=5)

params = {
    "exchange": "NSE",
    "symboltoken": "99926000",
    "interval": "FIVE_MINUTE",
    "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
    "todate": to_date.strftime("%Y-%m-%d %H:%M"),
}

response = obj.getCandleData(params)

if not response.get("status"):
    print("Failed to fetch candle data")
    exit()

df = calculate_indicators(response["data"])

print("\nLast 10 Candles with Indicators:\n")

print(
    df[[
        "time",
        "close",
        "EMA20",
        "EMA50",
        "EMA200",
        "RSI",
        "MACD",
        "MACD_SIGNAL",
        "VWAP"
    ]].tail(10)
)
