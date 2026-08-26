"""Fail-closed market-data routing with authenticated provider failover."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

from src.alternative_market_data import get_upstox_client
from src.option_chain import load_instruments


class MarketDataRouter:
    """Single production gateway for candles and live option quotes.

    The router never fabricates data. Provider selection is explicit, every
    successful response is tagged with its source, and callers receive no
    market data when all configured providers fail.
    """

    def __init__(self, angel_client):
        self.angel_client = angel_client
        self.upstox = get_upstox_client()
        self.mode = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
        self.stats = {
            "angel_attempts": 0, "angel_successes": 0, "angel_skipped_cooldown": 0,
            "upstox_attempts": 0, "upstox_successes": 0, "provider_failures": 0,
            "option_angel_attempts": 0, "option_angel_successes": 0,
            "option_upstox_attempts": 0, "option_upstox_successes": 0,
        }

    def _validate_mode(self) -> None:
        if self.mode not in {"auto", "angel", "upstox"}:
            raise ValueError("MARKET_DATA_PROVIDER must be auto, angel, or upstox")

    def _angel_allowed(self) -> bool:
        if self.mode == "upstox":
            return False
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
            return float(quote.get("ltp") or quote.get("last_price") or 0) > 0
        except (TypeError, ValueError):
            return False

    def get_candles(self, symbol: str, params: dict[str, Any], interval_minutes: int = 5) -> tuple[list[Any] | None, str]:
        self._validate_mode()
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

    def get_option_quote(self, exchange: str, token: str) -> tuple[dict[str, Any] | None, str]:
        """Fetch one option quote through the single provider gateway."""
        self._validate_mode()
        token = str(token or "").strip()
        exchange = str(exchange or "NFO").strip().upper()
        upstox_key = token if "|" in token else ""
        if self.mode != "angel" and self.upstox.available() and upstox_key:
            self.stats["option_upstox_attempts"] += 1
            try:
                quote = self.upstox.get_full_quote(upstox_key)
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Upstox option quote exception: {exc}")
                quote = None
            if self._valid_option_quote(quote):
                self.stats["option_upstox_successes"] += 1
                return self._normalize_upstox_option_quote(quote), "upstox"
        if self._angel_allowed():
            self.stats["option_angel_attempts"] += 1
            try:
                response = self.angel_client.get_market_data("FULL", {exchange: [token]})
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Angel One option quote exception: {exc}")
                response = None
            quote = self._extract_angel_quote(response)
            if quote is not None:
                self.stats["option_angel_successes"] += 1
                return quote, "angel_one"
        return None, "none"

    @staticmethod
    def _extract_angel_quote(response: Any) -> dict[str, Any] | None:
        if not isinstance(response, dict) or not response.get("status"):
            return None
        fetched = response.get("data", {}).get("fetched", [])
        return fetched[0] if isinstance(fetched, list) and fetched and isinstance(fetched[0], dict) else None

    @staticmethod
    def _normalize_upstox_option_quote(quote: dict[str, Any]) -> dict[str, Any]:
        depth = quote.get("depth") or {}
        buys, sells = depth.get("buy") or [], depth.get("sell") or []
        bid = float(buys[0].get("price", 0) or 0) if buys else 0.0
        ask = float(sells[0].get("price", 0) or 0) if sells else 0.0
        return {
            "ltp": float(quote.get("last_price", 0) or 0),
            "tradeVolume": quote.get("volume", 0), "opnInterest": quote.get("oi", 0),
            "totBuyQuan": quote.get("total_buy_quantity", 0), "totSellQuan": quote.get("total_sell_quantity", 0),
            "lastTradeQty": 0, "avgPrice": quote.get("average_price", 0), "netChange": quote.get("net_change", 0),
            "percentChange": 0.0,
            "depth": {"buy": [{"price": bid}] if bid > 0 else [], "sell": [{"price": ask}] if ask > 0 else []},
            "instrument_token": quote.get("instrument_token", ""), "timestamp": quote.get("timestamp"),
        }

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
            ltp, source = self.get_option_ltp(exchange, str(contract.get("symbol") or contract.get("contract") or ""), str(contract.get("token") or contract.get("symbolToken") or ""))
            item = dict(contract)
            item["ltp"], item["data_source"] = ltp, source
            results.append(item)
        return results

    @staticmethod
    def _expiry_date(value: Any) -> date | None:
        try:
            return datetime.strptime(str(value).strip().upper(), "%d%b%Y").date()
        except (TypeError, ValueError):
            return None

    def _select_angel_chain_contracts(self, symbol: str, expiry: str) -> list[dict[str, Any]]:
        """Build a bounded Angel NFO contract universe from the local master.

        Angel's FULL market-data endpoint accepts at most 50 tokens per call.
        ``current_week`` resolves to the nearest non-expired expiry; an
        explicit DDMMMYYYY expiry must match exactly. No remote instrument
        discovery or alternate-provider data is used here.
        """
        underlying = str(symbol or "").strip().upper()
        if not underlying:
            return []
        today = date.today()
        requested = str(expiry or "current_week").strip().upper()
        rows = []
        for item in load_instruments():
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")).strip().upper() != underlying:
                continue
            if str(item.get("exch_seg", "")).strip().upper() != "NFO":
                continue
            if str(item.get("instrumenttype", "")).strip().upper() not in {"OPTIDX", "OPTSTK"}:
                continue
            option_symbol = str(item.get("symbol", "")).strip().upper()
            if not option_symbol.endswith(("CE", "PE")):
                continue
            token = str(item.get("token", "")).strip()
            expiry_text = str(item.get("expiry", "")).strip().upper()
            expiry_date = self._expiry_date(expiry_text)
            if not token or expiry_date is None or expiry_date < today:
                continue
            if requested != "CURRENT_WEEK" and expiry_text != requested:
                continue
            try:
                strike = float(item.get("strike", 0)) / 100.0
            except (TypeError, ValueError):
                continue
            if strike <= 0:
                continue
            rows.append({
                "symbol": option_symbol,
                "token": token,
                "exchange": "NFO",
                "expiry": expiry_text,
                "strike": strike,
                "option_type": "CE" if option_symbol.endswith("CE") else "PE",
                "instrumenttype": str(item.get("instrumenttype", "")).upper(),
            })
        if not rows:
            return []
        if requested == "CURRENT_WEEK":
            nearest = min(self._expiry_date(row["expiry"]) for row in rows)
            rows = [row for row in rows if self._expiry_date(row["expiry"]) == nearest]
        rows.sort(key=lambda row: (row["strike"], row["option_type"], row["token"]))
        return rows[:50]

    def get_option_chain(self, symbol: str, expiry: str = "current_week") -> tuple[list[dict[str, Any]] | None, str]:
        """Fetch an option chain through Angel FULL market data in Angel mode.

        The instrument master supplies contract metadata; Angel supplies the
        live quote. In ``auto`` mode Upstox remains the explicit fallback.
        In ``angel`` mode there is never an Upstox fallback.
        """
        self._validate_mode()
        contracts = self._select_angel_chain_contracts(symbol, expiry)
        if self.mode != "upstox" and contracts and self._angel_allowed():
            self.stats["option_angel_attempts"] += 1
            tokens = [row["token"] for row in contracts]
            try:
                response = self.angel_client.get_market_data("FULL", {"NFO": tokens})
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Angel One option chain exception for {symbol}: {exc}")
                response = None
            quotes = self._quote_by_token(response)
            if quotes:
                chain = []
                for contract in contracts:
                    quote = quotes.get(contract["token"])
                    if not self._valid_option_quote(quote):
                        continue
                    item = dict(contract)
                    item["market_data"] = quote
                    item["data_source"] = "angel_one"
                    chain.append(item)
                if chain:
                    self.stats["option_angel_successes"] += 1
                    return chain, "angel_one"
            if response is not None:
                self.stats["provider_failures"] += 1
        if self.mode == "angel":
            return None, "none"
        if self.upstox.available():
            try:
                chain = self.upstox.get_option_chain(symbol, expiry=expiry)
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(f"[MARKET DATA] Upstox option chain exception for {symbol}: {exc}")
                chain = None
            if isinstance(chain, list) and chain:
                self.stats["option_upstox_attempts"] += 1
                self.stats["option_upstox_successes"] += 1
                return chain, "upstox"
        return None, "none"

    @staticmethod
    def _quote_by_token(response: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(response, dict) or not response.get("status"):
            return {}
        fetched = (response.get("data") or {}).get("fetched", [])
        if not isinstance(fetched, list):
            return {}
        result = {}
        for quote in fetched:
            if not isinstance(quote, dict):
                continue
            token = str(quote.get("symbolToken") or quote.get("instrument_token") or quote.get("token") or "").strip()
            if token:
                result[token] = quote
        return result

    def summary(self) -> dict[str, int]:
        return dict(self.stats)

    def provider_status(self) -> dict[str, Any]:
        upstox_status = self.upstox.status() if hasattr(self.upstox, "status") else {"available": bool(self.upstox.available())}
        try:
            angel_status = self.angel_client.market_data_status()
        except Exception as exc:
            angel_status = {"healthy": False, "status_error": str(exc)}
        return {"angel": angel_status, "upstox": upstox_status, "mode": self.mode}
