"""Optional independent Upstox market-data provider for PEREZ AI.

This module is deliberately independent of order execution.  When enabled,
PEREZ can use Upstox as a second market-data source and fail closed when the
source is configured but unavailable or materially disagrees with the primary
feed.

Credentials are environment-only:
    UPSTOX_ACCESS_TOKEN
    UPSTOX_ENABLED=true

Instrument mapping is environment-only JSON:
    UPSTOX_INSTRUMENT_KEYS_JSON='{"NIFTY":"NSE_INDEX|Nifty 50",...}'

The provider uses current V3 REST endpoints for LTP/intraday candles.  A
WebSocket collector can be layered on later without changing the normalized
interface consumed by the scanner.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://api.upstox.com/v3"
DEFAULT_TIMEOUT_SECONDS = 5.0


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return _truthy(os.getenv("UPSTOX_ENABLED", "false")) and bool(access_token())


def access_token() -> str:
    return os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


DEFAULT_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "NIFTYFPI": "NSE_INDEX|Nifty India FPI 150",
}


def instrument_keys() -> dict[str, str]:
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "").strip()
    if not raw:
        return dict(DEFAULT_INSTRUMENT_KEYS)

    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("JSON must be an object")
        return {
            str(k).upper().strip(): str(v).strip()
            for k, v in value.items()
            if str(v).strip()
        }
    except (TypeError, ValueError, json.JSONDecodeError):
        print("[UPSTOX] Invalid instrument JSON; using canonical mappings")
        return dict(DEFAULT_INSTRUMENT_KEYS)

def _headers() -> dict[str, str]:
    token = access_token()
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured")
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{BASE_URL}{path}",
        headers=_headers(),
        params=params,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Upstox returned a non-object response")
    if str(payload.get("status", "")).lower() not in {"success", "ok"}:
        raise RuntimeError(f"Upstox API unsuccessful response: {payload}")
    return payload


def get_ltp(instrument_key: str) -> float:
    encoded = quote(instrument_key, safe="")
    payload = _get(f"/market-quote/ltp?instrument_key={encoded}")
    data = payload.get("data") or {}
    for value in data.values():
        if isinstance(value, dict) and value.get("last_price") is not None:
            price = float(value["last_price"])
            if price > 0:
                return price
    raise RuntimeError(f"Upstox LTP missing for {instrument_key}")


def get_intraday_candles(instrument_key: str, interval_minutes: int = 5) -> list[list[Any]]:
    if interval_minutes < 1 or interval_minutes > 300:
        raise ValueError("Upstox intraday interval must be between 1 and 300 minutes")
    encoded = quote(instrument_key, safe="")
    payload = _get(f"/historical-candle/intraday/{encoded}/minutes/{interval_minutes}")
    candles = (payload.get("data") or {}).get("candles", [])
    if not isinstance(candles, list):
        raise RuntimeError("Upstox intraday response has invalid candles")
    return candles


def _parse_timestamp(raw: Any) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def get_latest_closed_candle(instrument_key: str, interval_minutes: int = 5) -> list[Any]:
    candles = get_intraday_candles(instrument_key, interval_minutes)
    if not candles:
        raise RuntimeError(f"No Upstox intraday candles for {instrument_key}")
    now = datetime.now(IST)
    bucket_minute = (now.minute // interval_minutes) * interval_minutes
    current_bucket = now.replace(minute=bucket_minute, second=0, microsecond=0)
    required_bucket = current_bucket - timedelta(minutes=interval_minutes)
    valid: list[tuple[datetime, list[Any]]] = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = _parse_timestamp(row[0])
            values = [float(x) for x in row[1:6]]
            if any(x < 0 for x in values) or values[3] <= 0:
                continue
            if ts.replace(second=0, microsecond=0) <= required_bucket:
                valid.append((ts, list(row)))
        except (TypeError, ValueError, IndexError):
            continue
    if not valid:
        raise RuntimeError(f"No closed Upstox {interval_minutes}-minute candle for {instrument_key}")
    valid.sort(key=lambda item: item[0])
    ts, row = valid[-1]
    age = (now - ts).total_seconds()
    if age < -60 or age > max(600, interval_minutes * 60 + 120):
        raise RuntimeError(f"Upstox candle is stale: age={age:.1f}s")
    return row


def get_snapshot(symbol: str) -> dict[str, Any]:
    symbol = str(symbol).upper().strip()
    key = instrument_keys().get(symbol)
    if not key:
        raise RuntimeError(f"No Upstox instrument key configured for {symbol}")
    candle = get_latest_closed_candle(key, 5)
    ltp = get_ltp(key)
    timestamp = _parse_timestamp(candle[0])
    close = float(candle[4])
    return {
        "provider": "upstox",
        "symbol": symbol,
        "instrument_key": key,
        "ltp": ltp,
        "closed_5m_close": close,
        "closed_5m_timestamp": timestamp.isoformat(),
        "candle_age_seconds": round((datetime.now(IST) - timestamp).total_seconds(), 1),
    }
