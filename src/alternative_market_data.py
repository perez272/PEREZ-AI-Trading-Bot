"""Alternative market-data provider used when Angel One is unavailable.

Upstox is an authenticated, broker-provided market-data source.  This module
only supplies OHLCV candles; all freshness, integrity, indicator, and trade
decision gates remain in the existing scanner.
"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests

UPSTOX_BASE_URL = "https://api.upstox.com/v3"
UPSTOX_TIMEOUT_SECONDS = float(os.getenv("UPSTOX_TIMEOUT_SECONDS", "8"))
UPSTOX_REQUEST_INTERVAL_SECONDS = float(os.getenv("UPSTOX_REQUEST_INTERVAL_SECONDS", "1.0"))

# Upstox instrument keys use ISINs for equities and named index instruments.
# The values can be overridden with UPSTOX_INSTRUMENT_KEYS_JSON if an account's
# instrument master uses a different key.
DEFAULT_INSTRUMENT_KEYS = {
    "SENSEX": "BSE_INDEX|SENSEX",
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|Nifty Midcap Select",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "INFY": "NSE_EQ|INE009A01021",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "AXISBANK": "NSE_EQ|INE238A01034",
}


def _env_instrument_keys() -> dict[str, str]:
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        import json
        value = json.loads(raw)
        return {str(k).upper(): str(v) for k, v in value.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        print("[UPSTOX] Invalid UPSTOX_INSTRUMENT_KEYS_JSON; using built-in mappings.")
        return {}


class UpstoxMarketData:
    """Small defensive wrapper around Upstox V3 intraday candle data."""

    provider_name = "upstox"

    def __init__(self, access_token: str | None = None):
        self.access_token = (access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()
        self.enabled = os.getenv("UPSTOX_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.instrument_keys = dict(DEFAULT_INSTRUMENT_KEYS)
        self.instrument_keys.update(_env_instrument_keys())
        self._last_request = 0.0
        self._session = requests.Session()

    def available(self) -> bool:
        return self.enabled and bool(self.access_token)

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "enabled": self.enabled,
            "configured": bool(self.access_token),
            "available": self.available(),
        }

    def _pace(self) -> None:
        remaining = UPSTOX_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def get_candles(self, symbol: str, interval_minutes: int = 5) -> list[list[Any]] | None:
        if not self.available():
            return None
        instrument_key = self.instrument_keys.get(symbol.upper())
        if not instrument_key:
            print(f"[UPSTOX] No instrument mapping for {symbol}; skipping fallback.")
            return None
        if not 1 <= int(interval_minutes) <= 300:
            raise ValueError("interval_minutes must be between 1 and 300")

        self._pace()
        encoded_key = quote(instrument_key, safe="")
        url = f"{UPSTOX_BASE_URL}/historical-candle/intraday/{encoded_key}/minutes/{int(interval_minutes)}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        try:
            response = self._session.get(url, headers=headers, timeout=UPSTOX_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            print(f"[UPSTOX] request failed for {symbol}: {exc}")
            return None
        if response.status_code != 200:
            print(f"[UPSTOX] HTTP {response.status_code} for {symbol}; fallback unavailable this cycle.")
            return None
        try:
            payload = response.json()
        except ValueError:
            print(f"[UPSTOX] invalid JSON response for {symbol}.")
            return None
        if str(payload.get("status", "")).lower() not in {"success", "ok"}:
            print(f"[UPSTOX] unsuccessful response for {symbol}.")
            return None
        candles = payload.get("data", {}).get("candles")
        return candles if isinstance(candles, list) else None


_upstox = UpstoxMarketData()


def get_upstox_client() -> UpstoxMarketData:
    return _upstox
