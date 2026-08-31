"""Optional independent Upstox market-data provider for PEREZ AI.

This module is deliberately independent of order execution. When enabled,
PEREZ can use Upstox as a second market-data source and fail closed when the
source is configured but unavailable or materially disagrees with the primary
feed.

Credentials are environment-only:
    UPSTOX_ACCESS_TOKEN
    UPSTOX_ENABLED=true

Instrument mapping is environment JSON, with safe built-in index defaults:
    UPSTOX_INSTRUMENT_KEYS_JSON='{"NIFTY":"NSE_INDEX|Nifty 50",...}'

The provider uses current V3 REST endpoints for LTP/intraday/historical
candles. A WebSocket collector can be layered later without changing the
normalized interface consumed by the scanner.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://api.upstox.com/v3"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
HISTORICAL_LOOKBACK_DAYS = max(15, int(os.getenv("UPSTOX_HISTORICAL_LOOKBACK_DAYS", "15")))
DEFAULT_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "NIFTYFPI": "NSE_INDEX|Nifty India FPI 150",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return _truthy(os.getenv("UPSTOX_ENABLED", "false")) and bool(access_token())


def access_token() -> str:
    return os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


def instrument_keys() -> dict[str, str]:
    result = dict(DEFAULT_INSTRUMENT_KEYS)
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "").strip()
    if not raw:
        return result
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return result
    if not isinstance(value, dict):
        return result
    result.update({str(k).upper().strip(): str(v).strip() for k, v in value.items() if str(v).strip()})
    return result


def _headers() -> dict[str, str]:
    token = access_token()
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN is not configured")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


_last_request = 0.0


def _pace() -> None:
    global _last_request
    interval = max(0.0, float(os.getenv("UPSTOX_REQUEST_INTERVAL_SECONDS", str(DEFAULT_REQUEST_INTERVAL_SECONDS))))
    remaining = interval - (time.monotonic() - _last_request)
    if remaining > 0:
        time.sleep(remaining)
    _last_request = time.monotonic()


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    _pace()
    response = requests.get(
        f"{BASE_URL}{path}",
        headers=_headers(),
        params=params,
        timeout=float(os.getenv("UPSTOX_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Upstox returned a non-object response")
    if str(payload.get("status", "")).lower() not in {"success", "ok"}:
        raise RuntimeError(f"Upstox API unsuccessful response: {payload}")
    return payload


def _normalize_candles(candles: Any) -> list[list[Any]]:
    if not isinstance(candles, list):
        return []
    valid: list[list[Any]] = []
    seen: set[str] = set()
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = _parse_timestamp(row[0])
            o, h, low, close, volume = (float(row[i]) for i in range(1, 6))
            if min(o, h, low, close) < 0 or close <= 0 or volume < 0:
                continue
            if h < max(o, low, close) or low > min(o, h, close):
                continue
            key = ts.isoformat()
            if key in seen:
                continue
            seen.add(key)
            valid.append([row[0], row[1], row[2], row[3], row[4], row[5]])
        except (TypeError, ValueError, IndexError):
            continue
    valid.sort(key=lambda row: _parse_timestamp(row[0]))
    return valid


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
    return _normalize_candles((payload.get("data") or {}).get("candles", []))


def get_historical_candles(
    symbol: str,
    interval_minutes: int = 5,
    lookback_days: int | None = None,
) -> list[list[Any]]:
    """Compatibility/public interface for multi-day V3 historical candles.

    ``symbol`` is the PEREZ universe name (for example ``NIFTY``), not an
    Angel instrument token. The endpoint is queried once, then today's
    intraday candles are merged so the newest closed candle is not lost.
    """
    key = instrument_keys().get(str(symbol).upper().strip())
    if not key:
        raise RuntimeError(f"No Upstox instrument key configured for {symbol}")
    if interval_minutes < 1 or interval_minutes > 300:
        raise ValueError("Upstox historical interval must be between 1 and 300 minutes")
    days = max(15, int(lookback_days if lookback_days is not None else HISTORICAL_LOOKBACK_DAYS))
    encoded = quote(key, safe="")
    today = datetime.now(IST).date()
    from_date = today - timedelta(days=days)
    payload = _get(
        f"/historical-candle/{encoded}/minutes/{interval_minutes}/{today.isoformat()}/{from_date.isoformat()}"
    )
    historical = _normalize_candles((payload.get("data") or {}).get("candles", []))
    try:
        intraday = get_intraday_candles(key, interval_minutes)
    except Exception as exc:
        print(f"[UPSTOX] Intraday merge skipped for {symbol}: {exc}")
        intraday = []
    merged = { _parse_timestamp(row[0]).isoformat(): row for row in historical + intraday }
    return sorted(merged.values(), key=lambda row: _parse_timestamp(row[0]))


def get_latest_closed_candle(instrument_key: str, interval_minutes: int = 5) -> list[Any]:
    candles = get_intraday_candles(instrument_key, interval_minutes)
    if not candles:
        raise RuntimeError(f"No Upstox intraday candles for {instrument_key}")
    now = datetime.now(IST)
    bucket_minute = (now.minute // interval_minutes) * interval_minutes
    current_bucket = now.replace(minute=bucket_minute, second=0, microsecond=0)
    required_bucket = current_bucket - timedelta(minutes=interval_minutes)
    valid = []
    for row in candles:
        try:
            ts = _parse_timestamp(row[0])
            if ts.replace(second=0, microsecond=0) <= required_bucket:
                valid.append((ts, row))
        except (TypeError, ValueError, IndexError):
            continue
    if not valid:
        raise RuntimeError(f"No closed Upstox {interval_minutes}-minute candle for {instrument_key}")
    valid.sort(key=lambda item: item[0])
    ts, row = valid[-1]
    bucket = ts.replace(minute=(ts.minute // interval_minutes) * interval_minutes, second=0, microsecond=0)
    candle_close = bucket + timedelta(minutes=interval_minutes)
    age = (now - candle_close).total_seconds()
    if age < -60 or age > max(600, interval_minutes * 60 + 120):
        raise RuntimeError(f"Upstox candle is stale: age={age:.1f}s")
    return row


def _parse_timestamp(raw: Any) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def get_snapshot(symbol: str) -> dict[str, Any]:
    symbol = str(symbol).upper().strip()
    key = instrument_keys().get(symbol)
    if not key:
        raise RuntimeError(f"No Upstox instrument key configured for {symbol}")
    candle = get_latest_closed_candle(key, 5)
    ltp = get_ltp(key)
    timestamp = _parse_timestamp(candle[0])
    bucket = timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0, microsecond=0)
    candle_close = bucket + timedelta(minutes=5)
    age = (datetime.now(IST) - candle_close).total_seconds()
    return {
        "provider": "upstox",
        "symbol": symbol,
        "instrument_key": key,
        "ltp": ltp,
        "closed_5m_close": float(candle[4]),
        "closed_5m_timestamp": timestamp.isoformat(),
        "candle_age_seconds": round(age, 1),
    }
