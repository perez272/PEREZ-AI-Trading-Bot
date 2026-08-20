"""Manual SmartAPI LTP smoke test.

This file is intentionally not a pytest test: importing it must never log in to
Angel One or consume API rate limits. Run it directly when a live smoke test is
wanted.
"""

from SmartApi import SmartConnect
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
import pyotp


def main():
    obj = SmartConnect(api_key=API_KEY)
    obj.generateSession(CLIENT_ID, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())
    symbol = "AXISBANK26JUL1240CE"
    token = "1138612"
    for exch in ["NFO", "NSE"]:
        print("\nTesting:", exch)
        try:
            print(obj.ltpData(exch, symbol, token))
        except Exception as exc:
            print(exc)


if __name__ == "__main__":
    main()
