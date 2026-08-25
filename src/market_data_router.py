"""Fail-closed market-data routing with authenticated provider failover."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.alternative_market_data import get_upstox_client


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
        return isinstance(response, dict) and bool(response.get("status")) and isinstance(response.get("data"), list) and bool(response.get("data"))

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

    def get_option_chain(
        self,
        symbol: str,
        expiry: str = "current_week",
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """
        Return a verified option chain through the production market-data
        gateway.

        Angel One path:
          instrument master -> expiry -> ATM strike window -> one batched
          getMarketData(FULL) request -> normalized chain.

        This deliberately avoids searchScrip and individual option requests.
        No contracts are fabricated. If the instrument master, underlying
        quote, expiry, or batched quote is unavailable, the method fails
        closed.
        """
        self._validate_mode()
        symbol = str(symbol or "").strip().upper()

        # Upstox remains available only when explicitly allowed by router mode.
        if self.mode != "angel" and self.upstox.available():
            try:
                chain = self.upstox.get_option_chain(symbol, expiry=expiry)
            except Exception as exc:
                self.stats["provider_failures"] += 1
                print(
                    f"[MARKET DATA] Upstox option chain exception "
                    f"for {symbol}: {exc}"
                )
                chain = None

            if isinstance(chain, list) and chain:
                return chain, "upstox"

        if self.mode == "upstox":
            return None, "none"

        if not self._angel_allowed():
            return None, "none"

        try:
            from src.option_chain import load_instruments

            instruments = load_instruments()
        except Exception as exc:
            self.stats["provider_failures"] += 1
            print(
                f"[MARKET DATA] Angel option chain instrument-master "
                f"load failed for {symbol}: {exc}"
            )
            return None, "none"

        if not isinstance(instruments, list) or not instruments:
            return None, "none"

        # Resolve the nearest valid future expiry from the verified
        # instrument master. Angel stores option strikes scaled by 100.
        today = datetime.now().date()
        option_rows = []

        for item in instruments:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip().upper()
            exchange = str(item.get("exch_seg", "")).strip().upper()
            instrument_type = str(
                item.get("instrumenttype", "")
            ).strip().upper()
            option_symbol = str(
                item.get("symbol", "")
            ).strip().upper()
            option_type = (
                "CE"
                if option_symbol.endswith("CE")
                else "PE"
                if option_symbol.endswith("PE")
                else ""
            )

            if name != symbol:
                continue
            if exchange != "NFO":
                continue
            if instrument_type not in ("OPTIDX", "OPTSTK"):
                continue
            if option_type not in ("CE", "PE"):
                continue

            expiry_text = str(item.get("expiry", "")).strip().upper()

            try:
                expiry_date = datetime.strptime(
                    expiry_text,
                    "%d%b%Y",
                ).date()
            except (TypeError, ValueError):
                continue

            if expiry_date < today:
                continue

            try:
                strike = float(item.get("strike", 0) or 0) / 100.0
            except (TypeError, ValueError):
                continue

            if strike <= 0:
                continue

            token = str(
                item.get("token")
                or item.get("symbolToken")
                or ""
            ).strip()

            if not token:
                continue

            option_rows.append(
                {
                    "item": item,
                    "expiry": expiry_text,
                    "expiry_date": expiry_date,
                    "strike": strike,
                    "option_type": option_type,
                    "token": token,
                    "symbol": option_symbol,
                }
            )

        if not option_rows:
            print(
                f"[MARKET DATA] Angel option master has no valid "
                f"future NFO contracts for {symbol}"
            )
            return None, "none"

        requested_expiry = str(expiry or "current_week").strip().upper()

        expiries = sorted(
            {row["expiry_date"] for row in option_rows}
        )

        if requested_expiry in ("", "CURRENT_WEEK", "WEEKLY"):
            selected_expiry_date = expiries[0]
        else:
            selected_expiry_date = None

            for candidate in expiries:
                if requested_expiry in (
                    candidate.strftime("%d%b%Y").upper(),
                    candidate.strftime("%Y-%m-%d"),
                    candidate.strftime("%d-%b-%Y").upper(),
                ):
                    selected_expiry_date = candidate
                    break

            if selected_expiry_date is None:
                print(
                    f"[MARKET DATA] Requested Angel expiry "
                    f"{expiry!r} unavailable for {symbol}"
                )
                return None, "none"

        expiry_rows = [
            row
            for row in option_rows
            if row["expiry_date"] == selected_expiry_date
        ]

        if not expiry_rows:
            return None, "none"

        # Resolve the underlying from the same verified instrument master.
        underlying = None

        for item in instruments:
            if not isinstance(item, dict):
                continue

            if (
                str(item.get("exch_seg", "")).strip().upper() == "NSE"
                and str(item.get("name", "")).strip().upper() == symbol
            ):
                token = str(
                    item.get("token")
                    or item.get("symbolToken")
                    or ""
                ).strip()

                trading_symbol = str(
                    item.get("symbol")
                    or item.get("tradingsymbol")
                    or symbol
                ).strip()

                if token:
                    underlying = {
                        "token": token,
                        "symbol": trading_symbol,
                    }
                    break

        if underlying is None:
            print(
                f"[MARKET DATA] Cannot resolve verified NSE "
                f"underlying token for {symbol}"
            )
            return None, "none"

        # One underlying quote determines the ATM center.
        try:
            spot_response = self.angel_client.get_ltp(
                "NSE",
                underlying["symbol"],
                underlying["token"],
            )
        except Exception as exc:
            self.stats["provider_failures"] += 1
            print(
                f"[MARKET DATA] Angel underlying LTP exception "
                f"for {symbol}: {exc}"
            )
            return None, "none"

        try:
            spot = float(
                (spot_response or {}).get("data", {}).get("ltp", 0)
                or 0
            )
        except (TypeError, ValueError, AttributeError):
            spot = 0.0

        if spot <= 0:
            print(
                f"[MARKET DATA] Invalid Angel underlying LTP "
                f"for {symbol}"
            )
            return None, "none"

        # Determine the natural strike interval from the actual master.
        strikes = sorted(
            {
                float(row["strike"])
                for row in expiry_rows
                if row["strike"] > 0
            }
        )

        if not strikes:
            return None, "none"

        # Pick the nearest actual strike as ATM.
        atm = min(strikes, key=lambda strike: abs(strike - spot))
        atm_index = strikes.index(atm)

        # Controlled window: 5 strikes either side of ATM.
        # This gives up to 11 strikes / 22 option tokens.
        low = max(0, atm_index - 5)
        high = min(len(strikes), atm_index + 6)
        selected_strikes = set(strikes[low:high])

        selected_rows = [
            row
            for row in expiry_rows
            if row["strike"] in selected_strikes
        ]

        # Never exceed a conservative single-request token count.
        selected_rows = selected_rows[:50]

        exchange_tokens = {
            "NFO": [row["token"] for row in selected_rows]
        }

        self.stats["option_angel_attempts"] += 1

        try:
            response = self.angel_client.get_market_data(
                "FULL",
                exchange_tokens,
            )
        except Exception as exc:
            self.stats["provider_failures"] += 1
            print(
                f"[MARKET DATA] Angel option-chain batch exception "
                f"for {symbol}: {exc}"
            )
            return None, "none"

        if not isinstance(response, dict) or not response.get("status"):
            self.stats["provider_failures"] += 1
            return None, "none"

        fetched = (
            response.get("data", {}).get("fetched", [])
            if isinstance(response.get("data"), dict)
            else []
        )

        if not isinstance(fetched, list) or not fetched:
            self.stats["provider_failures"] += 1
            return None, "none"

        quotes_by_token = {}

        for quote in fetched:
            if not isinstance(quote, dict):
                continue

            token = str(
                quote.get("symbolToken")
                or quote.get("instrument_token")
                or quote.get("token")
                or ""
            ).strip()

            if token:
                quotes_by_token[token] = quote

        chain_by_strike = {}

        for row in selected_rows:
            token = row["token"]
            quote = quotes_by_token.get(token)

            if not quote:
                continue

            try:
                ltp = float(
                    quote.get("ltp")
                    or quote.get("lastPrice")
                    or 0
                )
            except (TypeError, ValueError):
                continue

            if ltp <= 0:
                continue

            market_data = {
                "ltp": ltp,
                "bid_price": quote.get("bestBidPrice"),
                "ask_price": quote.get("bestAskPrice"),
                "volume": quote.get("tradeVolume"),
                "oi": quote.get("opnInterest"),
                "average_price": quote.get("avgPrice"),
                "net_change": quote.get("netChange"),
                "percent_change": quote.get("percentChange"),
                "last_trade_qty": quote.get("lastTradeQty"),
            }

            normalized_market = {
                "instrument_key": f"NFO|{token}",
                "trading_symbol": row["symbol"],
                "market_data": market_data,
                "option_greeks": {},
            }

            strike_key = float(row["strike"])
            chain_row = chain_by_strike.setdefault(
                strike_key,
                {
                    "expiry": row["expiry"],
                    "strike_price": strike_key,
                    "call_options": {},
                    "put_options": {},
                },
            )

            if row["option_type"] == "CE":
                chain_row["call_options"] = normalized_market
            else:
                chain_row["put_options"] = normalized_market

        chain = sorted(
            chain_by_strike.values(),
            key=lambda row: float(row["strike_price"]),
        )

        if not chain:
            self.stats["provider_failures"] += 1
            print(
                f"[MARKET DATA] Angel returned no valid option "
                f"quotes for {symbol}"
            )
            return None, "none"

        self.stats["option_angel_successes"] += 1

        print(
            f"[MARKET DATA] Angel option chain supplied {symbol}: "
            f"expiry={selected_expiry_date.strftime('%d%b%Y')} "
            f"spot={spot:.2f} atm={atm:.2f} "
            f"strikes={len(chain)} quotes={len(fetched)}"
        )

        return chain, "angel_one"

    def summary(self) -> dict[str, int]:
        return dict(self.stats)

    def provider_status(self) -> dict[str, Any]:
        upstox_status = self.upstox.status() if hasattr(self.upstox, "status") else {"available": bool(self.upstox.available())}
        try:
            angel_status = self.angel_client.market_data_status()
        except Exception as exc:
            angel_status = {"healthy": False, "status_error": str(exc)}
        return {"angel": angel_status, "upstox": upstox_status, "mode": self.mode}
