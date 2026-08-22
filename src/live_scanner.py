"""Optional read-only Angel One live quote scanner.

Importing this module does not load the broker SDK, log in, call the broker,
print output, or start a loop. Call ``scan_once()`` explicitly for one pass or
``run_forever()`` for the legacy five-second polling behavior.
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

import pyotp
from dotenv import load_dotenv

from src.watchlist import WATCHLIST

load_dotenv()


@lru_cache(maxsize=1)
def _get_client():
    from SmartApi import SmartConnect

    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")
    if not all([api_key, client_id, password, totp_secret]):
        raise RuntimeError("Missing Angel One credentials in .env")
    obj = SmartConnect(api_key=api_key)
    session = obj.generateSession(client_id, password, pyotp.TOTP(totp_secret).now())
    if not session.get("status"):
        raise RuntimeError(f"Angel One login failed: {session}")
    return obj


def scan_once():
    obj = _get_client()
    results = []
    for exchange, symbol, token in WATCHLIST:
        try:
            data = obj.ltpData(exchange, symbol, token)
            if data.get("status"):
                results.append({"exchange": exchange, "symbol": symbol, "token": token, "ltp": data["data"]["ltp"]})
            else:
                results.append({"exchange": exchange, "symbol": symbol, "token": token, "error": data})
        except Exception as exc:
            results.append({"exchange": exchange, "symbol": symbol, "token": token, "error": str(exc)})
    return results


def run_forever(interval_seconds: float = 5.0) -> None:
    print("Connected to Angel One")
    while True:
        print("=" * 70)
        for item in scan_once():
            if "ltp" in item:
                print(f"{item['symbol']:<22} {item['ltp']}")
            else:
                print(f"{item['symbol']:<22} {item['error']}")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_forever()
