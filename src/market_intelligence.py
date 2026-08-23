"""PEREZ AI market/option intelligence hardening layer.

This module adds evidence that was previously represented only by zero-filled
placeholders: broker-provided option Greeks/IV, OI-change persistence, PCR
context, live underlying-vs-candle divergence, and execution/trap diagnostics.
It is read-only and never places orders.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from src.market_scanner import get_client
from src.upgrade_config import MAX_SPREAD_PCT, MAX_SLIPPAGE_PCT

STATE_PATH = Path(os.getenv("PEREZ_INTELLIGENCE_STATE", "data/runtime/option_intelligence.json"))
RISK_FREE_RATE = float(os.getenv("PEREZ_RISK_FREE_RATE", "0.065"))
MAX_UNDERLYING_DIVERGENCE_PCT = float(os.getenv("PEREZ_MAX_UNDERLYING_DIVERGENCE_PCT", "0.60"))
MAX_IV_PCT = float(os.getenv("PEREZ_MAX_IV_PCT", "120"))
PCR_CACHE_SECONDS = 30.0
_GREEK_LOCK = Lock()
_PCR_CACHE = {"ts": 0.0, "data": {}}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_state() -> Dict[str, Any]:
    try:
        if STATE_PATH.exists():
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _expiry_year(expiry: str) -> Optional[datetime]:
    text = str(expiry or "").strip().upper()
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _black_scholes(spot: float, strike: float, years: float, rate: float, vol: float, option_type: str) -> Dict[str, float]:
    years = max(years, 1e-8)
    vol = max(vol, 1e-8)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    disc = math.exp(-rate * years)
    if option_type == "CE":
        price = spot * _normal_cdf(d1) - strike * disc * _normal_cdf(d2)
        delta = _normal_cdf(d1)
    else:
        price = strike * disc * _normal_cdf(-d2) - spot * _normal_cdf(-d1)
        delta = _normal_cdf(d1) - 1.0
    gamma = _normal_pdf(d1) / (spot * vol * math.sqrt(years))
    vega = spot * _normal_pdf(d1) * math.sqrt(years) / 100.0
    theta = (
        -(spot * _normal_pdf(d1) * vol) / (2.0 * math.sqrt(years))
        - rate * strike * disc * _normal_cdf(d2 if option_type == "CE" else -d2)
    ) / 365.0
    return {"price": price, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def _implied_volatility(market_price: float, spot: float, strike: float, years: float, option_type: str) -> Optional[float]:
    if min(market_price, spot, strike, years) <= 0:
        return None
    lo, hi = 1e-4, 5.0
    intrinsic = max(0.0, spot - strike) if option_type == "CE" else max(0.0, strike - spot)
    if market_price < intrinsic * 0.995:
        return None
    for _ in range(70):
        mid = (lo + hi) / 2.0
        value = _black_scholes(spot, strike, years, RISK_FREE_RATE, mid, option_type)["price"]
        if value > market_price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def _reserve_and_call(client, func, *args):
    """Use the bot's shared market-data limiter before non-quote endpoints."""
    if not client._reserve_market_data_request("_last_market_data_request", 1.0):
        return None
    return client._retry(func, *args)


def _fetch_greeks(symbol: str, expiry: str, strike: float, option_type: str) -> Dict[str, Any]:
    client = get_client()
    with _GREEK_LOCK:
        try:
            response = _reserve_and_call(client, client.api.optionGreek, {"name": symbol, "expirydate": expiry})
            rows = response.get("data") if isinstance(response, dict) and response.get("status") else None
            if not isinstance(rows, list):
                return {"available": False, "source": "angelone_option_greek", "error": "NO_GREEK_DATA"}
            best = None
            best_distance = float("inf")
            for row in rows:
                if str(row.get("optionType", "")).upper() != option_type.upper():
                    continue
                distance = abs(_num(row.get("strikePrice"), float("inf")) - strike)
                if distance < best_distance:
                    best, best_distance = row, distance
            if not best or best_distance > max(1.0, strike * 0.001):
                return {"available": False, "source": "angelone_option_greek", "error": "STRIKE_NOT_FOUND"}
            return {
                "available": True,
                "source": "angelone_option_greek",
                "delta": _num(best.get("delta")),
                "gamma": _num(best.get("gamma")),
                "theta": _num(best.get("theta")),
                "vega": _num(best.get("vega")),
                "iv_pct": _num(best.get("impliedVolatility")),
                "trade_volume": _num(best.get("tradeVolume")),
            }
        except Exception as exc:
            return {"available": False, "source": "angelone_option_greek", "error": repr(exc)}


def _fetch_pcr() -> Dict[str, Any]:
    now = time.monotonic()
    if now - _PCR_CACHE["ts"] < PCR_CACHE_SECONDS:
        return _PCR_CACHE["data"]
    client = get_client()
    try:
        response = _reserve_and_call(client, client.api.putCallRatio)
        rows = response.get("data") if isinstance(response, dict) and response.get("status") else None
        data = {}
        if isinstance(rows, list):
            for row in rows:
                symbol = str(row.get("tradingSymbol", "")).upper()
                pcr = _num(row.get("pcr"), -1.0)
                if symbol and pcr >= 0:
                    data[symbol] = pcr
        _PCR_CACHE.update(ts=now, data=data)
        return data
    except Exception:
        return _PCR_CACHE["data"]


def enrich_option_intelligence(candidate: Dict[str, Any], contract: Dict[str, Any]) -> Dict[str, Any]:
    """Return additional evidence and hard safety diagnostics."""
    out = dict(candidate)
    symbol = str(candidate.get("symbol", "")).upper()
    option_type = str(candidate.get("option_type", "")).upper()
    expiry = str(contract.get("expiry") or candidate.get("expiry") or "")
    strike = _num(contract.get("strike"))
    option_ltp = _num(out.get("ltp"))
    underlying_close = _num(candidate.get("close"))

    # Fresh underlying LTP is used as a divergence guard; a 5-minute candle is
    # not treated as a live spot price for option decisions.
    underlying_spot = 0.0
    try:
        from src.upgrade_config import SYMBOLS
        exchange, token = SYMBOLS.get(symbol, ("NSE", ""))
        quote = get_client().get_market_data("LTP", {exchange: [token]}) if token else None
        fetched = quote.get("data", {}).get("fetched", []) if isinstance(quote, dict) and quote.get("status") else []
        if fetched:
            underlying_spot = _num(fetched[0].get("ltp"))
    except Exception:
        underlying_spot = 0.0

    divergence_pct = 0.0
    if underlying_spot > 0 and underlying_close > 0:
        divergence_pct = abs(underlying_spot - underlying_close) / underlying_close * 100.0
    out["underlying_spot"] = underlying_spot
    out["underlying_divergence_pct"] = divergence_pct

    expiry_dt = _expiry_year(expiry)
    now = datetime.now(timezone.utc)
    years = max(1.0 / (365.0 * 24.0), ((expiry_dt - now).total_seconds() / (365.0 * 24.0 * 3600.0)) if expiry_dt else 0.0)

    greeks = _fetch_greeks(symbol, expiry, strike, option_type) if strike > 0 and expiry else {"available": False, "error": "MISSING_STRIKE_OR_EXPIRY"}
    if not greeks.get("available") and underlying_spot > 0 and strike > 0 and option_ltp > 0 and years > 0:
        iv = _implied_volatility(option_ltp, underlying_spot, strike, years, option_type)
        if iv is not None and iv <= 5.0:
            calc = _black_scholes(underlying_spot, strike, years, RISK_FREE_RATE, iv, option_type)
            greeks = {
                "available": True,
                "source": "local_black_scholes_from_live_ltp",
                "delta": calc["delta"],
                "gamma": calc["gamma"],
                "theta": calc["theta"],
                "vega": calc["vega"],
                "iv_pct": iv * 100.0,
            }
    out.update({
        "greeks_available": bool(greeks.get("available")),
        "greeks_source": greeks.get("source", ""),
        "delta": _num(greeks.get("delta")),
        "gamma": _num(greeks.get("gamma")),
        "theta": _num(greeks.get("theta")),
        "vega": _num(greeks.get("vega")),
        "iv_pct": _num(greeks.get("iv_pct")),
    })

    # Persist observations so OI/IV changes are real changes, never invented.
    state = _load_state()
    key = f"{symbol}|{expiry}|{strike:.4f}|{option_type}"
    previous = state.get(key, {}) if isinstance(state.get(key), dict) else {}
    current_oi = _num(out.get("open_interest"))
    current_iv = _num(out.get("iv_pct"))
    previous_oi = _num(previous.get("oi"))
    previous_iv = _num(previous.get("iv"))
    oi_change_pct = ((current_oi - previous_oi) / previous_oi * 100.0) if previous_oi > 0 else 0.0
    iv_change_pct = ((current_iv - previous_iv) / previous_iv * 100.0) if previous_iv > 0 and current_iv > 0 else 0.0
    out["oi_change_pct"] = oi_change_pct
    out["iv_change_pct"] = iv_change_pct
    out["oi_change_available"] = previous_oi > 0
    out["iv_change_available"] = previous_iv > 0 and current_iv > 0
    state[key] = {"oi": current_oi, "iv": current_iv, "ltp": option_ltp, "ts": time.time()}
    try:
        _save_state(state)
    except OSError:
        pass

    pcr_map = _fetch_pcr()
    pcr = -1.0
    for k, value in pcr_map.items():
        if symbol in k:
            pcr = value
            break
    out["pcr"] = pcr
    out["pcr_available"] = pcr >= 0

    # Evidence scores: only award points when the underlying evidence exists.
    iv = out["iv_pct"]
    out["iv_score"] = 5.0 if 0 < iv <= MAX_IV_PCT else 0.0
    out["oi_change_score"] = min(8.0, abs(oi_change_pct) / 5.0) if previous_oi > 0 else 0.0
    out["volatility_score"] = 5.0 if out["greeks_available"] and iv > 0 else 0.0

    # Cheap-option traps: price alone is never sufficient. Penalize a long
    # option whose IV is already extreme or whose underlying quote diverges
    # materially from the candle used for the signal.
    reasons = []
    if divergence_pct > MAX_UNDERLYING_DIVERGENCE_PCT:
        reasons.append("UNDERLYING_LTP_CANDLE_DIVERGENCE")
    if iv > MAX_IV_PCT:
        reasons.append("EXTREME_IV")
    if out.get("spread_pct", 999.0) > MAX_SPREAD_PCT:
        reasons.append("WIDE_SPREAD")
    if out.get("slippage_pct", 999.0) > MAX_SLIPPAGE_PCT:
        reasons.append("HIGH_SLIPPAGE")
    if option_ltp <= 0:
        reasons.append("INVALID_OPTION_PRICE")
    if not out.get("greeks_available"):
        reasons.append("GREEKS_UNAVAILABLE")

    # Directional trap check: the option itself must be moving in the intended
    # direction and its delta must have the correct sign.
    pct = _num(out.get("percent_change"))
    delta = _num(out.get("delta"))
    if pct <= 0:
        reasons.append("OPTION_TAPE_NOT_CONFIRMING")
    if option_type == "CE" and delta <= 0:
        reasons.append("CE_DELTA_INVALID")
    if option_type == "PE" and delta >= 0:
        reasons.append("PE_DELTA_INVALID")

    # PCR is contextual, not a standalone directional trigger. Only reject
    # extreme contradiction; absence of PCR does not create fake evidence.
    if pcr >= 0:
        out["pcr_context"] = "PUT_HEAVY" if pcr > 1.35 else "CALL_HEAVY" if pcr < 0.65 else "BALANCED"
    else:
        out["pcr_context"] = "UNAVAILABLE"

    # Approximate transaction drag using the observable spread and slippage.
    cost_drag = max(0.0, _num(out.get("spread_pct"))) + max(0.0, _num(out.get("slippage_pct")))
    out["cost_drag_pct"] = cost_drag
    if cost_drag >= 2.0:
        reasons.append("EXECUTION_COST_TOO_HIGH")

    out["intelligence_reasons"] = reasons
    out["intelligence_hard_fail"] = bool(reasons)
    out["intelligence_ready"] = bool(out.get("greeks_available")) and not reasons
    out["intelligence_score"] = round(
        100.0
        - min(25.0, divergence_pct * 20.0)
        - min(20.0, max(0.0, iv - 40.0) * 0.5)
        - min(15.0, cost_drag * 5.0)
        + (5.0 if previous_oi > 0 else 0.0),
        2,
    )
    return out
