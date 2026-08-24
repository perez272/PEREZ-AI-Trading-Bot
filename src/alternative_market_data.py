"""Alternative authenticated market-data provider used when Angel One is unavailable."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests

UPSTOX_BASE_URL = "https://api.upstox.com/v3"
UPSTOX_V2_BASE_URL = "https://api.upstox.com/v2"
UPSTOX_TIMEOUT_SECONDS = float(os.getenv("UPSTOX_TIMEOUT_SECONDS", "8"))
UPSTOX_REQUEST_INTERVAL_SECONDS = float(os.getenv("UPSTOX_REQUEST_INTERVAL_SECONDS", "1.0"))

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
    """Defensive wrapper around Upstox V3 candles and V2 option APIs."""

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
        return {"provider": self.provider_name, "enabled": self.enabled, "configured": bool(self.access_token), "available": self.available()}

    def _pace(self) -> None:
        remaining = UPSTOX_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.available():
            return None
        self._pace()
        try:
            response = self._session.get(url, params=params, headers={"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}, timeout=UPSTOX_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            print(f"[UPSTOX] request failed: {exc}")
            return None
        if response.status_code != 200:
            print(f"[UPSTOX] HTTP {response.status_code}; provider unavailable for this request.")
            return None
        try:
            payload = response.json()
        except ValueError:
            print("[UPSTOX] invalid JSON response.")
            return None
        if str(payload.get("status", "")).lower() not in {"success", "ok"}:
            print("[UPSTOX] unsuccessful response.")
            return None
        return payload

    def get_candles(self, symbol: str, interval_minutes: int = 5) -> list[list[Any]] | None:
        if not self.available():
            return None
        instrument_key = self.instrument_keys.get(symbol.upper())
        if not instrument_key:
            print(f"[UPSTOX] No instrument mapping for {symbol}; skipping fallback.")
            return None
        if not 1 <= int(interval_minutes) <= 300:
            raise ValueError("interval_minutes must be between 1 and 300")
        encoded_key = quote(instrument_key, safe="")
        payload = self._get(f"{UPSTOX_BASE_URL}/historical-candle/intraday/{encoded_key}/minutes/{int(interval_minutes)}")
        candles = payload.get("data", {}).get("candles") if payload else None
        return candles if isinstance(candles, list) else None

    def get_option_chain(self, symbol: str, expiry: str = "current_week") -> list[dict[str, Any]] | None:
        if not self.available():
            return None
        underlying_key = self.instrument_keys.get(symbol.upper())
        if not underlying_key:
            return None
        payload = self._get(f"{UPSTOX_V2_BASE_URL}/option/chain", {"instrument_key": underlying_key, "expiry_date": expiry})
        data = payload.get("data") if payload else None
        return data if isinstance(data, list) else None

    def resolve_affordable_option(self, symbol: str, spot: float, option_type: str, max_premium: float) -> dict[str, Any] | None:
        chain = self.get_option_chain(symbol)
        if not chain or option_type not in {"CE", "PE"}:
            return None
        candidates = []
        for row in chain:
            try:
                strike = float(row.get("strike_price"))
                option = row.get("call_options" if option_type == "CE" else "put_options") or {}
                instrument_key = option.get("instrument_key")
                market = option.get("market_data") or {}
                ltp = float(market.get("ltp", 0) or 0)
                bid = float(market.get("bid_price", 0) or 0)
                ask = float(market.get("ask_price", 0) or 0)
                volume = float(market.get("volume", 0) or 0)
                oi = float(market.get("oi", 0) or 0)
                if not instrument_key or ltp <= 0 or ltp > max_premium or strike <= 0:
                    continue
                spread_pct = ((ask - bid) / ltp * 100.0) if bid > 0 and ask >= bid else 999.0
                if spread_pct > 5.0:
                    continue
                candidates.append((abs(strike - float(spot)), -volume, -oi, spread_pct, row, option, ltp))
            except (TypeError, ValueError):
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:4])
        _, _, _, spread_pct, row, option, ltp = candidates[0]
        return {
            "status": "CONTRACT VALID",
            "option_type": option_type,
            "contract": option.get("trading_symbol") or row.get("trading_symbol", ""),
            "exchange": "NFO" if str(option.get("instrument_key", "")).startswith("NSE_FO|") else "BFO",
            "token": option.get("instrument_key", ""),
            "expiry": row.get("expiry", ""),
            "strike": float(row.get("strike_price")),
            "lotsize": int(option.get("lot_size") or row.get("lot_size") or 0),
            "ltp": ltp,
            "spread_pct": round(spread_pct, 3),
            "volume": float((option.get("market_data") or {}).get("volume", 0) or 0),
            "oi": float((option.get("market_data") or {}).get("oi", 0) or 0),
            "data_source": "upstox_option_chain",
        }


_upstox = UpstoxMarketData()


def get_upstox_client() -> UpstoxMarketData:
    return _upstox
