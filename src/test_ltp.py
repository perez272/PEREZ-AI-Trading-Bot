"""Manual live-LTP diagnostic.

This module intentionally performs no broker login during pytest collection.
Run it directly only when an operator explicitly wants a live diagnostic.
"""


def main():
    from SmartApi import SmartConnect
    from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
    import pyotp

    obj = SmartConnect(api_key=API_KEY)
    obj.generateSession(CLIENT_ID, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())

    symbol = "AXISBANK26JUL1240CE"
    token = "1138612"
    for exch in ("NFO", "NSE"):
        print(f"\nTesting: {exch}")
        try:
            print(obj.ltpData(exch, symbol, token))
        except Exception as exc:
            print(exc)


if __name__ == "__main__":
    main()
