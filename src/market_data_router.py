"""Fail-closed market-data routing with authenticated provider failover."""

from __future__ import annotations

import os
from typing import Any

from src.alternative_market_data import get_upstox_client
from src.fyers_market_data import get_fyers_client


class MarketDataRouter:
    """Prefer Angel One, then Upstox, then FYERS for data-only failover.

    The router never manufactures candles and never relaxes freshness rules.
    Provider payloads are still passed through the existing market-data
    validation layer before indicators or trade-decision logic consume them.
    """

    def __init__(self, angel_client):
        self.angel_client = angel_client
        self.upstox = get_upstox_client()
        self.fyers = get_fyers_client()
        self.mode = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
        self.stats = {
            "angel_attempts": 0,
            "angel_successes": 0,
            "upstox_attempts": 0,
            "upstox_successes": 0,
            "fyers_attempts": 0,
            "fyers_successes": 0,
        }

    def _angel_allowed(self) -> bool:
        if self.mode in {"upstox", "fyers"}:
            return False
        try:
            status = self.angel_client.market_data_status()
        except Exception:
            return True
        return status.get("cooldown_remaining", 0) <= 0 and status.get("requests_remaining", 1) > 0

    def get_candles(
        self,
        symbol: str,
        params: dict[str, Any],
        interval_minutes: int = 5,
    ) -> tuple[list[Any] | None, str]:
        if self.mode not in {"auto", "angel", "upstox", "fyers"}:
            raise ValueError("MARKET_DATA_PROVIDER must be auto, angel, upstox, or fyers")

        if self._angel_allowed():
            self.stats["angel_attempts"] += 1
            try:
                response = self.angel_client.get_candles(params)
            except Exception as exc:
                print(f"[MARKET DATA] Angel One exception for {symbol}: {exc}")
                response = None
            if isinstance(response, dict) and response.get("status") and isinstance(response.get("data"), list):
                self.stats["angel_successes"] += 1
                return response["data"], "angel_one"

        if self.mode == "angel":
            return None, "none"

        if self.mode in {"auto", "upstox"} and self.upstox.available():
            self.stats["upstox_attempts"] += 1
            try:
                candles = self.upstox.get_candles(symbol, interval_minutes=interval_minutes)
            except Exception as exc:
                print(f"[MARKET DATA] Upstox exception for {symbol}: {exc}")
                candles = None
            if candles:
                self.stats["upstox_successes"] += 1
                print(f"[MARKET DATA] Upstox fallback supplied {symbol} after Angel One unavailable.")
                return candles, "upstox"

        if self.mode in {"auto", "fyers"} and self.fyers.available():
            self.stats["fyers_attempts"] += 1
            try:
                candles = self.fyers.get_candles(symbol, interval_minutes=interval_minutes)
            except Exception as exc:
                print(f"[MARKET DATA] FYERS exception for {symbol}: {exc}")
                candles = None
            if candles:
                self.stats["fyers_successes"] += 1
                print(f"[MARKET DATA] FYERS fallback supplied {symbol} after primary sources unavailable.")
                return candles, "fyers"

        return None, "none"

    def summary(self) -> dict[str, int]:
        return dict(self.stats)
