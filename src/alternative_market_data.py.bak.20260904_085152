"""Alternative authenticated market-data provider used when Angel One is unavailable."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

UPSTOX_BASE_URL = "https://api.upstox.com/v3"
UPSTOX_V2_BASE_URL = "https://api.upstox.com/v2"
IST = timezone(timedelta(hours=5, minutes=30))

UPSTOX_TIMEOUT_SECONDS = float(os.getenv("UPSTOX_TIMEOUT_SECONDS", "8"))
UPSTOX_REQUEST_INTERVAL_SECONDS = float(os.getenv("UPSTOX_REQUEST_INTERVAL_SECONDS", "1.0"))
UPSTOX_HISTORICAL_LOOKBACK_DAYS = max(15, int(os.getenv("UPSTOX_HISTORICAL_LOOKBACK_DAYS", "15")))
INSTRUMENT_FILE = Path("data/instruments.json")

DEFAULT_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "NIFTYFPI": "NSE_INDEX|Nifty India FPI 150",
}


def _env_instrument_keys() -> dict[str, str]:
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            return {}
        return {str(k).upper(): str(v) for k, v in value.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        print("[UPSTOX] Invalid UPSTOX_INSTRUMENT_KEYS_JSON; using built-in mappings.")
        return {}


def _local_instrument_keys() -> dict[str, str]:
    """Never derive Upstox keys from the Angel instrument master."""
    return {}


class UpstoxMarketData:
    """Defensive wrapper around Upstox V3 historical candles and V2 option APIs."""

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
            response = self._session.get(url, params=params, headers={"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}, timeout=UPSTOX_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            print(f"[UPSTOX] request failed: {exc}")
            return None
        if response.status_code != 200:
            body = ""
            try:
                body = response.text.strip()
            except Exception:
                body = ""
            print(
                f"[UPSTOX] HTTP {response.status_code}; "
                f"url={response.url}; "
                f"response={body[:1000]}"
            )
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

    @staticmethod
    def _normalize_candles(candles: Any) -> list[list[Any]] | None:
        if not isinstance(candles, list):
            return None
        valid: list[list[Any]] = []
        seen: set[str] = set()
        for row in candles:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                timestamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                o, h, low, close = (float(row[i]) for i in range(1, 5))
                volume = float(row[5])
                if min(o, h, low, close, volume) < 0 or close <= 0:
                    continue
                if h < max(o, low, close) or low > min(o, h, close):
                    continue
                key = timestamp.isoformat()
                if key in seen:
                    continue
                seen.add(key)
                # Canonical scanner schema: timestamp, open, high, low, close, volume.
                # Upstox may return additional fields; do not pass them downstream.
                valid.append([row[0], row[1], row[2], row[3], row[4], row[5]])
            except (TypeError, ValueError, IndexError):
                continue
        valid.sort(key=lambda row: datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")))
        return valid or None

    def get_candles(self, symbol: str, interval_minutes: int = 5) -> list[list[Any]] | None:
        """Return multi-day history plus today's intraday candles, merged by timestamp."""
        if not self.available():
            return None
        instrument_key = self.instrument_keys.get(symbol.upper())
        if not instrument_key:
            print(f"[UPSTOX] No instrument mapping for {symbol}; skipping fallback.")
            return None
        interval = int(interval_minutes)
        if not 1 <= interval <= 300:
            raise ValueError("interval_minutes must be between 1 and 300")
        encoded_key = quote(instrument_key, safe="")
        today = datetime.now().date()
        from_date = today - timedelta(days=UPSTOX_HISTORICAL_LOOKBACK_DAYS)

        historical_url = f"{UPSTOX_BASE_URL}/historical-candle/{encoded_key}/minutes/{interval}/{today.isoformat()}/{from_date.isoformat()}"
        historical_payload = self._get(historical_url)
        historical = historical_payload.get("data", {}).get("candles") if historical_payload else None
        merged_rows = self._normalize_candles(historical) or []

        # Today's intraday endpoint supplies the freshest current-session candles.
        intraday_url = f"{UPSTOX_BASE_URL}/historical-candle/intraday/{encoded_key}/minutes/{interval}"
        intraday_payload = self._get(intraday_url)
        intraday = intraday_payload.get("data", {}).get("candles") if intraday_payload else None
        merged_rows.extend(self._normalize_candles(intraday) or [])

        deduped: dict[str, list[Any]] = {}
        for row in merged_rows:
            try:
                ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            except (TypeError, ValueError, IndexError):
                continue
            deduped[ts.isoformat()] = row
        normalized = sorted(deduped.values(), key=lambda row: datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")))
        if normalized:
            print(f"[UPSTOX] Historical fallback returned {len(normalized)} {interval}-minute candles for {symbol} (lookback={UPSTOX_HISTORICAL_LOOKBACK_DAYS}d).")
        return normalized or None

    # Compatibility API used by diagnostics/legacy callers.
    def get_historical_candles(self, symbol: str, interval_minutes: int = 5) -> list[list[Any]] | None:
        """Backward-compatible alias for :meth:`get_candles`."""
        return self.get_candles(symbol, interval_minutes=interval_minutes)

    def get_option_chain(self, symbol: str, expiry: str | None = None) -> list[dict[str, Any]] | None:
        if not self.available():
            return None

        underlying_key = self.instrument_keys.get(symbol.upper())
        if not underlying_key:
            print(f"[UPSTOX] No underlying instrument mapping for {symbol}.")
            return None

        # Upstox option-chain requires an actual expiry date (YYYY-MM-DD).
        # Resolve the legacy/default "current_week" request from the
        # currently available option contracts instead of skipping the chain.
        resolved_expiry = None if not expiry or expiry == "current_week" else str(expiry)

        if resolved_expiry is None:
            contracts_payload = self._get(
                f"{UPSTOX_V2_BASE_URL}/option/contract",
                {"instrument_key": underlying_key},
            )
            contracts = contracts_payload.get("data") if contracts_payload else None

            if isinstance(contracts, list):
                expiries = sorted(
                    {
                        str(row.get("expiry"))
                        for row in contracts
                        if isinstance(row, dict)
                        and row.get("expiry")
                        and len(str(row.get("expiry"))) == 10
                        and str(row.get("expiry"))[4] == "-"
                        and str(row.get("expiry"))[7] == "-"
                    }
                )
                if expiries:
                    resolved_expiry = expiries[0]

            if not resolved_expiry:
                print(
                    f"[UPSTOX] Option chain skipped for {symbol}: "
                    "could not resolve an available YYYY-MM-DD expiry."
                )
                return None

            print(
                f"[UPSTOX] Resolved {symbol} option-chain expiry "
                f"{resolved_expiry} from option contracts."
            )

        payload = self._get(
            f"{UPSTOX_V2_BASE_URL}/option/chain",
            {
                "instrument_key": underlying_key,
                "expiry_date": resolved_expiry,
            },
        )

        data = payload.get("data") if payload else None
        return data if isinstance(data, list) else None

    def get_full_quote(self, instrument_key: str) -> dict[str, Any] | None:
        if not self.available() or not instrument_key or "|" not in instrument_key:
            return None
        payload = self._get(f"{UPSTOX_V2_BASE_URL}/market-quote/quotes", {"instrument_key": instrument_key})
        data = payload.get("data") if payload else None
        if not isinstance(data, dict) or not data:
            return None
        quote = next(iter(data.values()))
        return quote if isinstance(quote, dict) else None

    def get_snapshot(self, symbol: str) -> dict[str, Any]:
        """Return a compact validated Upstox market snapshot for integrity checks."""
        symbol = str(symbol).upper().strip()

        if not self.available():
            raise RuntimeError("Upstox market data is unavailable")

        instrument_key = self.instrument_keys.get(symbol)
        if not instrument_key:
            raise RuntimeError(
                f"No Upstox instrument key configured for {symbol}"
            )

        candles = self.get_candles(symbol, interval_minutes=5)
        if not candles:
            raise RuntimeError(f"No Upstox 5m candles returned for {symbol}")

        candle = candles[-1]
        if not isinstance(candle, (list, tuple)) or len(candle) < 5:
            raise RuntimeError(f"Invalid Upstox candle returned for {symbol}")

        timestamp_raw = candle[0]
        close = float(candle[4])

        timestamp = datetime.fromisoformat(
            str(timestamp_raw).replace("Z", "+00:00")
        )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        else:
            timestamp = timestamp.astimezone(IST)

        quote = self.get_full_quote(instrument_key) or {}

        ltp = None
        for key in ("last_price", "last_traded_price", "ltp"):
            value = quote.get(key)
            if value is not None:
                try:
                    ltp = float(value)
                    break
                except (TypeError, ValueError):
                    pass

        if ltp is None:
            raise RuntimeError(f"No Upstox LTP returned for {symbol}")

        age = (datetime.now(IST) - timestamp).total_seconds()

        return {
            "provider": "upstox",
            "symbol": symbol,
            "instrument_key": instrument_key,
            "ltp": ltp,
            "closed_5m_close": close,
            "closed_5m_timestamp": timestamp.isoformat(),
            "candle_age_seconds": round(age, 1),
        }

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

        lot_size = option.get("lot_size") or row.get("lot_size") or 0
        contract_symbol = option.get("trading_symbol") or row.get("trading_symbol", "")
        contract_expiry = str(row.get("expiry", ""))

        # Upstox option-chain legs do not reliably expose lot_size/trading_symbol.
        # Enrich the selected contract from the authoritative option-contract API.
        if not lot_size and instrument_key:
            contracts_payload = self._get(
                f"{UPSTOX_V2_BASE_URL}/option/contract",
                {"instrument_key": self.instrument_keys[symbol.upper()]},
            )
            contracts = contracts_payload.get("data") if contracts_payload else None
            if isinstance(contracts, list):
                for contract_row in contracts:
                    if not isinstance(contract_row, dict):
                        continue
                    if str(contract_row.get("instrument_key", "")) != instrument_key:
                        continue
                    if contract_expiry and str(contract_row.get("expiry", "")) != contract_expiry:
                        continue
                    lot_size = contract_row.get("lot_size") or 0
                    contract_symbol = contract_row.get("trading_symbol") or contract_symbol
                    break

        return {
            "status": "CONTRACT VALID", "option_type": option_type,
            "contract": contract_symbol,
            "exchange": exchange, "token": instrument_key, "expiry": contract_expiry,
            "strike": float(row.get("strike_price")), "lotsize": int(lot_size),
            "ltp": ltp, "spread_pct": round(spread_pct, 3),
            "volume": float((option.get("market_data") or {}).get("volume", 0) or 0),
            "oi": float((option.get("market_data") or {}).get("oi", 0) or 0),
            "iv": float(greeks.get("iv", 0) or 0), "delta": float(greeks.get("delta", 0) or 0),
            "gamma": float(greeks.get("gamma", 0) or 0), "theta": float(greeks.get("theta", 0) or 0),
            "vega": float(greeks.get("vega", 0) or 0), "data_source": "upstox_option_chain",
        }


_upstox = UpstoxMarketData()


def get_upstox_client() -> UpstoxMarketData:
    return _upstox
