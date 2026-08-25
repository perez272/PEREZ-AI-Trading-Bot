"""Alternative authenticated market-data provider used when Angel One is unavailable."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

UPSTOX_BASE_URL = "https://api.upstox.com/v3"
UPSTOX_V2_BASE_URL = "https://api.upstox.com/v2"
UPSTOX_TIMEOUT_SECONDS = float(os.getenv("UPSTOX_TIMEOUT_SECONDS", "8"))
UPSTOX_REQUEST_INTERVAL_SECONDS = float(os.getenv("UPSTOX_REQUEST_INTERVAL_SECONDS", "1.0"))
INSTRUMENT_FILE = Path("data/instruments.json")

DEFAULT_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|Nifty Midcap Select",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "NIFTYFPI": "NSE_INDEX|Nifty India FPI 150",
}


def _env_instrument_keys() -> dict[str, str]:
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return {str(k).upper(): str(v) for k, v in value.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        print("[UPSTOX] Invalid UPSTOX_INSTRUMENT_KEYS_JSON; using built-in mappings.")
        return {}


def _local_instrument_keys() -> dict[str, str]:
    """Use current index mappings from the local instrument master when present."""
    if not INSTRUMENT_FILE.exists():
        return {}
    try:
        data = json.loads(INSTRUMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    result = {}
    aliases = {
        "NIFTY": {"NIFTY", "NIFTY 50"},
        "BANKNIFTY": {"BANKNIFTY", "NIFTY BANK"},
        "FINNIFTY": {"FINNIFTY", "NIFTY FIN SERVICE", "NIFTY FINANCIAL SERVICES"},
        "MIDCPNIFTY": {"MIDCPNIFTY", "NIFTY MIDCAP SELECT"},
        "NIFTYNXT50": {"NIFTYNXT50", "NIFTY NEXT 50"},
        "NIFTYFPI": {"NIFTYFPI", "NIFTY INDIA FPI 150"},
    }
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or str(item.get("exch_seg", "")).upper() != "NSE":
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        name = str(item.get("name", "")).strip().upper()
        token = str(item.get("token", "")).strip()
        if not token:
            continue
        for canonical, accepted in aliases.items():
            if symbol in accepted or name in accepted:
                result[canonical] = f"NSE_INDEX|{name or symbol}"
    return result


class UpstoxMarketData:
    """Defensive wrapper around Upstox V3 candles and V2 option APIs."""

    provider_name = "upstox"

    def __init__(self, access_token: str | None = None):
        self.access_token = (access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()
        self.enabled = os.getenv("UPSTOX_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self._last_request_at = 0.0

    def available(self) -> bool:
        return bool(self.enabled and self.access_token)

    def _headers(self):
        return {"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}

    def _get(self, url, params=None):
        if not self.available():
            return None
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < UPSTOX_REQUEST_INTERVAL_SECONDS:
            time.sleep(UPSTOX_REQUEST_INTERVAL_SECONDS - elapsed)
        response = requests.get(url, headers=self._headers(), params=params, timeout=UPSTOX_TIMEOUT_SECONDS)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()

    def get_candles(self, symbol: str, interval_minutes: int = 5):
        if not self.available():
            return None
        key = self.instrument_key(symbol)
        if not key:
            return None
        encoded = quote(key, safe="")
        data = self._get(f"{UPSTOX_BASE_URL}/historical-candle/{encoded}/minutes/{interval_minutes}/latest")
        candles = (data or {}).get("data", {}).get("candles", [])
        return candles if isinstance(candles, list) else None

    def get_full_quote(self, instrument_key: str):
        if not self.available() or not instrument_key:
            return None
        encoded = quote(instrument_key, safe="")
        data = self._get(f"{UPSTOX_V2_BASE_URL}/market-quote/quotes", params={"instrument_key": instrument_key})
        if not isinstance(data, dict):
            return None
        values = data.get("data") or {}
        if isinstance(values, dict):
            return next(iter(values.values()), None)
        return None

    def instrument_key(self, symbol: str) -> str | None:
        name = str(symbol or "").strip().upper()
        return _env_instrument_keys().get(name) or _local_instrument_keys().get(name) or DEFAULT_INSTRUMENT_KEYS.get(name)


def get_upstox_client() -> UpstoxMarketData:
    return UpstoxMarketData()
