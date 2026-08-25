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
        self.enabled = os.getenv("UPSTOX_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.instrument_keys = dict(DEFAULT_INSTRUMENT_KEYS)
        self.instrument_keys.update(_local_instrument_keys())
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
            response = self._session.get(
                url,
                params=params,
                headers={"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"},
                timeout=UPSTOX_TIMEOUT_SECONDS,
            )
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
        """Return Upstox's exchange-backed put/call chain.

        Upstox accepts relative expiry keywords such as current_week, so the
        caller does not need to hard-code a calendar date.
        """
        if not self.available():
            return None
        underlying_key = self.instrument_keys.get(symbol.upper())
        if not underlying_key:
            print(f"[UPSTOX] No underlying instrument mapping for {symbol}.")
            return None
        payload = self._get(
            f"{UPSTOX_V2_BASE_URL}/option/chain",
            {"instrument_key": underlying_key, "expiry_date": expiry},
        )
        data = payload.get("data") if payload else None
        return data if isinstance(data, list) else None

    def get_full_quote(self, instrument_key: str) -> dict[str, Any] | None:
        """Get one full exchange quote using an Upstox instrument key."""
        if not self.available() or not instrument_key or "|" not in instrument_key:
            return None
        payload = self._get(
            f"{UPSTOX_V2_BASE_URL}/market-quote/quotes",
            {"instrument_key": instrument_key},
        )
        data = payload.get("data") if payload else None
        if not isinstance(data, dict) or not data:
            return None
        # Upstox returns a dict keyed by its instrument representation.
        quote = next(iter(data.values()))
        return quote if isinstance(quote, dict) else None

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
                greeks = option.get("option_greeks") or {}
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
                candidates.append((abs(strike - float(spot)), -volume, -oi, spread_pct, row, option, ltp, greeks))
            except (TypeError, ValueError):
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:4])
        _, _, _, spread_pct, row, option, ltp, greeks = candidates[0]
        instrument_key = str(option.get("instrument_key", ""))
        exchange = "NFO" if instrument_key.startswith("NSE_FO|") else "BFO" if instrument_key.startswith("BSE_FO|") else ""
        return {
            "status": "CONTRACT VALID",
            "option_type": option_type,
            "contract": option.get("trading_symbol") or row.get("trading_symbol", ""),
            "exchange": exchange,
            "token": instrument_key,
            "expiry": row.get("expiry", ""),
            "strike": float(row.get("strike_price")),
            "lotsize": int(option.get("lot_size") or row.get("lot_size") or 0),
            "ltp": ltp,
            "spread_pct": round(spread_pct, 3),
            "volume": float((option.get("market_data") or {}).get("volume", 0) or 0),
            "oi": float((option.get("market_data") or {}).get("oi", 0) or 0),
            "iv": float(greeks.get("iv", 0) or 0),
            "delta": float(greeks.get("delta", 0) or 0),
            "gamma": float(greeks.get("gamma", 0) or 0),
            "theta": float(greeks.get("theta", 0) or 0),
            "vega": float(greeks.get("vega", 0) or 0),
            "data_source": "upstox_option_chain",
        }


_upstox = UpstoxMarketData()


def get_upstox_client() -> UpstoxMarketData:
    return _upstox
