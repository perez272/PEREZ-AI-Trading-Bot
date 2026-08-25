"""Fail-closed market-data routing with authenticated provider failover."""

from __future__ import annotations

import os
from typing import Any

from src.alternative_market_data import get_upstox_client


class MarketDataRouter:
    """Route verified market-data requests across configured legitimate providers.

    ``auto`` keeps Angel One as the first provider and routes around a provider
    failure/cooldown to Upstox. The router never manufactures or relaxes data;
    the scanner's freshness/integrity gates remain authoritative before any
    indicator or trade-decision code is reached.
    """

    def __init__(self, angel_client):
        self.angel_client = angel_client
        self.upstox = get_upstox_client()
        self.mode = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
        self.stats = {
            "angel_attempts": 0,
            "angel_successes": 0,
            "angel_skipped_cooldown": 0,
            "upstox_attempts": 0,
            "upstox_successes": 0,
            "provider_failures": 0,
        }

    def _angel_allowed(self) -> bool:
        if self.mode == "upstox":
            return False
        try:
            status = self.angel_client.market_data_status()
        except Exception:
            # A status endpoint failure must not make Angel unusable; the
            # actual request is still protected by the exception handler below.
            return True
        cooldown = float(status.get("cooldown_remaining", 0) or 0)
        remaining = int(status.get("requests_remaining", 1) or 0)
        if cooldown > 0 or remaining <= 0:
            self.stats["angel_skipped_cooldown"] += 1
            return False
        return True

    @staticmethod
    def _valid_payload(response: Any) -> bool:
        return (
            isinstance(response, dict)
            and bool(response.get("status"))
            and isinstance(response.get("data"), list)
            and bool(response.get("data"))
        )

    def get_candles(
        self,
        symbol: str,
        params: dict[str, Any],
        interval_minutes: int = 5,
    ) -> tuple[list[Any] | None, str]:
        if self.mode not in {"auto", "angel", "upstox"}:
            raise ValueError("MARKET_DATA_PROVIDER must be auto, angel, or upstox")

        # Angel is attempted when healthy. A cooldown is a provider-local
        # condition, not a global market-data stop.
        if self._angel_allowed():
            self.stats["angel_attempts"] += 1
            try:
                response = self.angel_client.get_candles(params)
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Angel One exception for {symbol}: {exc}")
                response = None
            if self._valid_payload(response):
                self.stats["angel_successes"] += 1
                return response["data"], "angel_one"
            if response is not None:
                self.stats["provider_failures"] += 1

        if self.mode == "angel":
            return None, "none"

        # Upstox is an independent recovery path. It is attempted whenever
        # Angel is unavailable, rate-limited, unhealthy, or returns unusable
        # data. No decision threshold is changed by this fallback.
        if self.upstox.available():
            self.stats["upstox_attempts"] += 1
            try:
                candles = self.upstox.get_candles(symbol, interval_minutes=interval_minutes)
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Upstox exception for {symbol}: {exc}")
                candles = None
            if isinstance(candles, list) and candles:
                self.stats["upstox_successes"] += 1
                print(f"[MARKET DATA] Upstox fallback supplied {symbol} after Angel One unavailable.")
                return candles, "upstox"
            if candles is not None:
                self.stats["provider_failures"] += 1

        return None, "none"

    def summary(self) -> dict[str, int]:
        return dict(self.stats)

    def provider_status(self) -> dict[str, Any]:
        upstox_status = self.upstox.status() if hasattr(self.upstox, "status") else {"available": bool(self.upstox.available())}
        try:
            angel_status = self.angel_client.market_data_status()
        except Exception as exc:
            angel_status = {"healthy": False, "status_error": str(exc)}
        return {"angel": angel_status, "upstox": upstox_status, "mode": self.mode}
