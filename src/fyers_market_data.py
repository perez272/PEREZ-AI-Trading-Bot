"""Optional FYERS API v3 market-data provider for PEREZ AI.

Data-only integration: this adapter never places orders. It uses FYERS v3
Quotes and History endpoints and exposes the same small candle interface used
by the market-data router. Credentials remain environment-only:

    FYERS_ENABLED=true
    FYERS_APP_ID=<app id>
    FYERS_ACCESS_TOKEN=<access token>
    FYERS_SYMBOLS_JSON='{"NIFTY":"NSE:NIFTY50-INDEX"}'

FYERS documents the v3 data host as https://api-t1.fyers.in/data and uses an
Authorization header in the form <app_id>:<access_token>.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import requests

BASE_URL = "https://api-t1.fyers.in/data"
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("FYERS_TIMEOUT_SECONDS", "8"))
DEFAULT_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "RELIANCE": "NSE:RELIANCE-EQ",
    "TCS": "NSE:TCS-EQ",
    "INFY": "NSE:INFY-EQ",
    "HDFCBANK": "NSE:HDFCBANK-EQ",
    "ICICIBANK": "NSE:ICICIBANK-EQ",
    "SBIN": "NSE:SBIN-EQ",
    "AXISBANK": "NSE:AXISBANK-EQ",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _symbol_map() -> dict[str, str]:
    mapping = dict(DEFAULT_SYMBOLS)
    raw = os.getenv("FYERS_SYMBOLS_JSON", "").strip()
    if not raw:
        return mapping
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return mapping
    if isinstance(value, dict):
        mapping.update({str(k).upper().strip(): str(v).strip() for k, v in value.items() if str(v).strip()})
    return mapping


class FyersMarketData:
    provider_name = "fyers"

    def __init__(self, app_id: str | None = None, access_token: str | None = None):
        self.app_id = (app_id or os.getenv("FYERS_APP_ID", "")).strip()
        self.access_token = (access_token or os.getenv("FYERS_ACCESS_TOKEN", "")).strip()
        self.enabled = _truthy(os.getenv("FYERS_ENABLED", "false"))
        self.symbols = _symbol_map()
        self._session = requests.Session()

    def available(self) -> bool:
        return self.enabled and bool(self.app_id) and bool(self.access_token)

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "enabled": self.enabled,
            "configured": bool(self.app_id and self.access_token),
            "available": self.available(),
        }

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available():
            return None
        try:
            response = self._session.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={
                    "Authorization": f"{self.app_id}:{self.access_token}",
                    "Accept": "application/json",
                },
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[FYERS] request failed: {exc}")
            return None
        if not isinstance(payload, dict) or str(payload.get("s", "")).lower() != "ok":
            print(f"[FYERS] unsuccessful response: {payload}")
            return None
        return payload

    def get_candles(self, symbol: str, interval_minutes: int = 5) -> list[list[Any]] | None:
        if not self.available():
            return None
        if not 1 <= int(interval_minutes) <= 240:
            raise ValueError("FYERS interval_minutes must be between 1 and 240")
        fyers_symbol = self.symbols.get(str(symbol).upper().strip())
        if not fyers_symbol:
            print(f"[FYERS] No symbol mapping for {symbol}; skipping fallback.")
            return None
        today = date.today()
        payload = self._get(
            "/history",
            {
                "symbol": fyers_symbol,
                "resolution": str(int(interval_minutes)),
                "date_format": "1",
                "range_from": (today - timedelta(days=1)).isoformat(),
                "range_to": today.isoformat(),
                "cont_flag": "0",
                "oi_flag": "0",
            },
        )
        candles = payload.get("candles") if payload else None
        if not isinstance(candles, list):
            return None
        valid: list[list[Any]] = []
        for row in candles:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                ts = int(row[0])
                o, h, low, close, volume = map(float, row[1:6])
                if ts <= 0 or min(o, h, low, close) <= 0 or h < max(o, low, close) or low > min(o, h, close):
                    continue
                if volume < 0:
                    continue
                valid.append([ts, o, h, low, close, volume])
            except (TypeError, ValueError):
                continue
        valid.sort(key=lambda row: row[0])
        return valid

    def get_ltp(self, symbol: str) -> float | None:
        if not self.available():
            return None
        fyers_symbol = self.symbols.get(str(symbol).upper().strip())
        if not fyers_symbol:
            return None
        payload = self._get("/quotes", {"symbols": fyers_symbol})
        data = payload.get("d") if payload else None
        if not isinstance(data, list) or not data:
            return None
        value = data[0].get("v") if isinstance(data[0], dict) else None
        if isinstance(value, dict) and value.get("lp") is not None:
            try:
                ltp = float(value["lp"])
                return ltp if ltp > 0 else None
            except (TypeError, ValueError):
                return None
        return None


_fyers = FyersMarketData()


def get_fyers_client() -> FyersMarketData:
    return _fyers
