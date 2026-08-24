"""Fail-closed market-data routing with authenticated provider failover."""

from __future__ import annotations

import os
from typing import Any

from src.alternative_market_data import get_upstox_client


class MarketDataRouter:
    """Prefer Angel One, then use Upstox when Angel cannot provide data.

    The router never manufactures candles and never relaxes freshness rules.
    Every returned payload is raw provider data and is validated by the existing
    scanner before it reaches indicators or trade-decision logic.
    """

    def __init__(self, angel_client):
        self.angel_client = angel_client
        self.upstox = get_upstox_client()
        self.mode = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
        self.stats = {
            "angel_attempts": 0,
            "angel_successes": 0,
            "upstox_attempts": 0,
            "upstox_successes": 0,
        }

    def _angel_allowed(self) -> bool:
        if self.mode == "upstox":
            return False
        try:
            status = self.angel_client.market_data_status()
        except Exception:
            return True
        return status.get("cooldown_remaining", 0) <= 0 and status.get("requests_remaining", 1) > 0

    def get_candles(self, symbol: str, exchange: str, token: str, interval: str = "FIVE_MINUTE") -> tuple[list[Any] | None, str]:
        if self.mode not in {"auto", "angel", "upstox"}:
            raise ValueError("MARKET_DATA_PROVIDER must be auto, angel, or upstox")

        if self._angel_allowed():
            self.stats["angel_attempts"] += 1
            try:
                response = self.angel_client.get_candles({
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": interval,
                    "fromdate": "",
                    "todate": "",
                })
            except Exception as exc:
                print(f"[MARKET DATA] Angel One exception for {symbol}: {exc}")
                response = None
            if isinstance(response, dict) and response.get("status") and isinstance(response.get("data"), list):
                self.stats["angel_successes"] += 1
                return response["data"], "angel_one"

        if self.mode == "angel":
            return None, "none"

        if self.upstox.available():
            self.stats["upstox_attempts"] += 1
            candles = self.upstox.get_candles(symbol, interval_minutes=5)
            if candles:
                self.stats["upstox_successes"] += 1
                print(f"[MARKET DATA] Upstox fallback supplied {symbol} after Angel One unavailable.")
                return candles, "upstox"

        return None, "none"

    def summary(self) -> dict[str, int]:
        return dict(self.stats)
