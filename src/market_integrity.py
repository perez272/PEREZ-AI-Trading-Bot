"""Adversarial market-integrity checks used before any paper trade."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict

from src.market_data_validation import validate_against_upstox

MAX_CANDLE_AGE_SECONDS = 420.0
MAX_SCORE_JUMP = 30
MIN_OPTION_LIQUIDITY = 1.0


def validate_candidate(candidate: Dict[str, Any], now: datetime | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not candidate or candidate.get("market_data_fresh") is not True:
        reasons.append("MARKET_DATA_NOT_FRESH")
    age = candidate.get("candle_age_seconds")
    try:
        if age is None or float(age) < 0 or float(age) > MAX_CANDLE_AGE_SECONDS:
            reasons.append("CANDLE_TOO_OLD")
    except (TypeError, ValueError):
        reasons.append("INVALID_CANDLE_AGE")
    if not candidate.get("candle_bucket"):
        reasons.append("MISSING_CANDLE_BUCKET")
    if candidate.get("signal") not in ("BUY CE", "BUY PE"):
        reasons.append("INVALID_SIGNAL")
    if candidate.get("mtf_aligned") is not True:
        reasons.append("MTF_NOT_ALIGNED")
    direction = str(candidate.get("m15_trend", "")).upper()
    h1 = str(candidate.get("h1_trend", "")).upper()
    signal = candidate.get("signal")
    if signal == "BUY CE" and not (direction == "BULLISH" and h1 == "BULLISH"):
        reasons.append("CE_DIRECTION_MISMATCH")
    if signal == "BUY PE" and not (direction == "BEARISH" and h1 == "BEARISH"):
        reasons.append("PE_DIRECTION_MISMATCH")
    if candidate.get("score", 0) < 0 or candidate.get("score", 0) > 100:
        reasons.append("INVALID_SCORE")
    if candidate.get("volume_ratio", 0) is not None:
        try:
            if float(candidate.get("volume_ratio", 0)) < 0:
                reasons.append("INVALID_VOLUME_RATIO")
        except (TypeError, ValueError):
            reasons.append("INVALID_VOLUME_RATIO")

    # Optional independent Upstox validation. When explicitly enabled, a
    # missing token, missing instrument mapping, stale response, or material
    # disagreement is a hard no-trade condition. This prevents a single broker
    # feed from becoming the sole source of truth.
    if candidate and candidate.get("symbol") and candidate.get("close") is not None:
        upstox_ok, details = validate_against_upstox(candidate["symbol"], float(candidate["close"]))
        candidate["upstox_validation"] = details
        candidate["upstox_data_valid"] = upstox_ok
        if not upstox_ok:
            reasons.append(f"UPSTOX_VALIDATION_{details.get('status', 'FAILED')}")

    return not reasons, reasons


def validate_option_integrity(candidate: Dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if candidate.get("live_market_data") is not True:
        reasons.append("LIVE_OPTION_DATA_REQUIRED")
    try:
        ltp = float(candidate.get("ltp", 0))
        bid = float(candidate.get("best_bid", 0))
        ask = float(candidate.get("best_ask", 0))
    except (TypeError, ValueError):
        return False, ["INVALID_OPTION_QUOTE"]
    if ltp <= 0 or bid <= 0 or ask <= 0 or bid > ask:
        reasons.append("INVALID_ORDER_BOOK")
    if candidate.get("spread_pct", 999) > 2.0:
        reasons.append("SPREAD_TOO_WIDE")
    if candidate.get("slippage_pct", 999) > 1.0:
        reasons.append("SLIPPAGE_TOO_HIGH")
    if candidate.get("volume", 0) <= 0:
        reasons.append("NO_LIVE_VOLUME")
    if candidate.get("open_interest", 0) <= 0:
        reasons.append("NO_LIVE_OI")
    if candidate.get("buy_quantity", 0) + candidate.get("sell_quantity", 0) <= 0:
        reasons.append("NO_LIVE_DEPTH")
    return not reasons, reasons
