"""Fail-closed Angel One-only market-data gateway."""
from __future__ import annotations

from typing import Any


class MarketDataRouter:
    """Single market-data gateway.

    Angel One is the only provider. No secondary provider is queried, and no
    synthetic data is ever returned. Rate-limit/cooldown failures fail closed.
    """

    def __init__(self, angel_client):
        self.angel_client = angel_client
        self.mode = "angel"
        self.stats = {
            "angel_attempts": 0,
            "angel_successes": 0,
            "angel_skipped_cooldown": 0,
            "upstox_attempts": 0,
            "upstox_successes": 0,
            "provider_failures": 0,
            "option_angel_attempts": 0,
            "option_angel_successes": 0,
            "option_upstox_attempts": 0,
            "option_upstox_successes": 0,
        }

    def _validate_mode(self) -> None:
        # Kept as a compatibility guard: this gateway deliberately has one
        # provider and ignores MARKET_DATA_PROVIDER/upstox configuration.
        if self.mode != "angel":
            raise ValueError("Angel One is the only supported market-data provider")

    def _angel_allowed(self) -> bool:
        try:
            status = self.angel_client.market_data_status()
        except Exception:
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

    @staticmethod
    def _valid_option_quote(quote: Any) -> bool:
        if not isinstance(quote, dict):
            return False
        try:
            return float(quote.get("ltp") or 0) > 0
        except (TypeError, ValueError):
            return False

    def get_candles(self, symbol: str, params: dict[str, Any], interval_minutes: int = 5) -> tuple[list[Any] | None, str]:
        self._validate_mode()
        if not self._angel_allowed():
            return None, "none"
        self.stats["angel_attempts"] += 1
        try:
            response = self.angel_client.get_candles(params)
        except Exception as exc:
            self.stats["provider_failures"] += 1
            print(f"[MARKET DATA] Angel One exception for {symbol}: {exc}")
            return None, "none"
        if self._valid_payload(response):
            self.stats["angel_successes"] += 1
            return response["data"], "angel_one"
        if response is not None:
            self.stats["provider_failures"] += 1
        return None, "none"

    def get_option_quote(self, exchange: str, token: str) -> tuple[dict[str, Any] | None, str]:
        """Fetch one option quote from Angel One only."""
        self._validate_mode()
        token = str(token or "").strip()
        exchange = str(exchange or "NFO").strip().upper()
        if not token or not self._angel_allowed():
            return None, "none"
        self.stats["option_angel_attempts"] += 1
        try:
            response = self.angel_client.get_market_data("FULL", {exchange: [token]})
        except Exception as exc:
            self.stats["provider_failures"] += 1
            print(f"[MARKET DATA] Angel One option quote exception: {exc}")
            return None, "none"
        quote = self._extract_angel_quote(response)
        if self._valid_option_quote(quote):
            self.stats["option_angel_successes"] += 1
            return quote, "angel_one"
        return None, "none"

    @staticmethod
    def _extract_angel_quote(response: Any) -> dict[str, Any] | None:
        if not isinstance(response, dict) or not response.get("status"):
            return None
        fetched = (response.get("data") or {}).get("fetched", [])
        return fetched[0] if isinstance(fetched, list) and fetched and isinstance(fetched[0], dict) else None

    def get_option_ltp(self, exchange: str, symbol: str, token: str) -> tuple[float | None, str]:
        quote, source = self.get_option_quote(exchange, token)
        if not quote:
            return None, source
        try:
            ltp = float(quote.get("ltp", 0) or 0)
        except (TypeError, ValueError):
            return None, source
        return (ltp if ltp > 0 else None), source

    def get_option_ltp_batch(self, exchange: str, contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for contract in contracts:
            ltp, source = self.get_option_ltp(
                exchange,
                str(contract.get("symbol") or contract.get("contract") or ""),
                str(contract.get("token") or contract.get("symbolToken") or ""),
            )
            item = dict(contract)
            item["ltp"], item["data_source"] = ltp, source
            results.append(item)
        return results

    def get_option_chain(self, symbol: str, expiry: str = "current_week") -> tuple[list[dict[str, Any]] | None, str]:
        # Chain discovery is intentionally not delegated to a secondary
        # provider. The Tier-1 observer builds an Angel FULL quote batch from
        # the Angel instrument master and current Angel candle spot.
        self._validate_mode()
        return None, "none"

    def summary(self) -> dict[str, int]:
        return dict(self.stats)

    def provider_status(self) -> dict[str, Any]:
        try:
            angel_status = self.angel_client.market_data_status()
        except Exception as exc:
            angel_status = {"healthy": False, "status_error": str(exc)}
        return {
            "angel": angel_status,
            "upstox": {"enabled": False, "available": False, "reason": "disabled: Angel One only"},
            "mode": "angel",
        }
