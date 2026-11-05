"""Read-only Upstox market-intelligence snapshot for the dashboard.

Only symbols with verified Upstox instrument keys are queried. No order APIs
are imported or called. Missing credentials/mappings produce an explicit
unavailable status rather than demo or fabricated market values.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from src.alternative_market_data import UpstoxMarketData

IST = timezone(timedelta(hours=5, minutes=30))
SECTORS = {
    "RELIANCE": "Energy", "ONGC": "Energy", "NTPC": "Energy",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "AXISBANK": "Banking", "KOTAKBANK": "Banking",
    "INFY": "IT", "TCS": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "LT": "Industrials", "BHARTIARTL": "Telecom",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _configured_symbols(client: UpstoxMarketData) -> list[str]:
    raw = os.getenv("PEREZ_MARKET_INTELLIGENCE_SYMBOLS", "").strip()
    requested = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if requested:
        return [s for s in requested if s in client.instrument_keys]
    # Use only equity keys explicitly present in the Upstox key map.
    return sorted(s for s, key in client.instrument_keys.items()
                  if "|" in key and not key.startswith("NSE_INDEX|"))


def _quote_value(quote: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(quote.get(key))
        if value is not None:
            return value
    return None


def build_snapshot() -> dict[str, Any]:
    now = datetime.now(IST).isoformat()
    client = UpstoxMarketData()
    status = client.status()
    if not status.get("available"):
        return {
            "status": "UNAVAILABLE", "provider": "upstox",
            "reason": "Upstox credentials/provider are not available to dashboard process.",
            "as_of": now, "symbols": [], "options": [], "sectors": [],
            "source": "Upstox API", "demo": False,
        }

    symbols = _configured_symbols(client)
    if not symbols:
        return {
            "status": "NEEDS_INSTRUMENT_MAPPING", "provider": "upstox",
            "reason": "No equity instrument keys configured. Add verified NSE_EQ keys in UPSTOX_INSTRUMENT_KEYS_JSON; do not guess keys.",
            "as_of": now, "symbols": [], "options": [], "sectors": [],
            "source": "Upstox API", "demo": False,
        }

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for symbol in symbols[:80]:
        key = client.instrument_keys.get(symbol)
        quote = client.get_full_quote(key) or {}
        ltp = _quote_value(quote, "last_price", "ltp")
        if ltp is None:
            failures.append(symbol)
            continue
        close = _quote_value(quote, "ohlc", "close")
        if isinstance(quote.get("ohlc"), dict):
            close = _number(quote["ohlc"].get("close"))
        change = ((ltp - close) / close * 100) if close and close > 0 else None
        volume = _quote_value(quote, "volume")
        avg_volume = _quote_value(quote, "average_volume")
        rows.append({
            "symbol": symbol, "sector": SECTORS.get(symbol, "Other"),
            "price": ltp, "change_pct": round(change, 3) if change is not None else None,
            "volume": volume, "average_volume": avg_volume,
            "relative_volume": round(volume / avg_volume, 2) if volume and avg_volume else None,
            "open_interest": _quote_value(quote, "oi", "open_interest"),
            "buy_qty": _quote_value(quote, "total_buy_qty"),
            "sell_qty": _quote_value(quote, "total_sell_qty"),
            "source": "Upstox", "as_of": now,
        })

    # Option-chain observations are descriptive only; OI change is not a
    # directional buyer/writer classification.
    option_rows: list[dict[str, Any]] = []
    for symbol in symbols[:12]:
        chain = client.get_option_chain(symbol)
        if not chain:
            continue
        for item in chain:
            if not isinstance(item, dict):
                continue
            call = item.get("call_options") or {}
            put = item.get("put_options") or {}
            for side, leg in (("CE", call), ("PE", put)):
                md = leg.get("market_data") or {}
                greeks = leg.get("option_greeks") or {}
                ltp = _number(md.get("ltp"))
                volume = _number(md.get("volume"))
                oi = _number(md.get("oi"))
                if ltp is None:
                    continue
                option_rows.append({
                    "symbol": symbol, "side": side,
                    "strike": _number(item.get("strike_price")),
                    "expiry": item.get("expiry"),
                    "ltp": ltp, "volume": volume, "oi": oi,
                    "iv": _number(greeks.get("iv")),
                    "delta": _number(greeks.get("delta")),
                    "instrument_key": leg.get("instrument_key"),
                })
    option_rows.sort(key=lambda x: (x.get("volume") or 0), reverse=True)

    sector_totals: dict[str, dict[str, float]] = {}
    for row in rows:
        sector = row["sector"]
        item = sector_totals.setdefault(sector, {"count": 0, "change_sum": 0})
        item["count"] += 1
        if row["change_pct"] is not None:
            item["change_sum"] += row["change_pct"]
    sectors = [
        {"sector": k, "stocks": int(v["count"]),
         "avg_change_pct": round(v["change_sum"] / v["count"], 3)}
        for k, v in sorted(sector_totals.items())
    ]
    return {
        "status": "LIVE" if rows else "NO_QUOTES",
        "provider": "upstox", "source": "Upstox API",
        "as_of": now, "demo": False,
        "reason": None if rows else "No valid live quotes returned for configured symbols.",
        "symbols": rows, "options": option_rows[:100], "sectors": sectors,
        "failed_symbols": failures, "configured_symbols": len(symbols),
    }
