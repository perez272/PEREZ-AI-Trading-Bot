"""Index momentum/scalp strategy for fast CE/PE opportunities.

This module is deliberately broker-agnostic. It consumes already validated,
closed-candle scanner candidates and applies a second, stricter momentum gate.
It never creates orders and never treats a cheap option premium as a signal.
"""

from __future__ import annotations

from datetime import time
from typing import Any, Iterable


INDEX_SYMBOLS = {"SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY"}
ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 45)
MIN_SCORE = 72


def _num(candidate: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(candidate.get(key, default))
        return value if value == value else default
    except (TypeError, ValueError):
        return default


def _signal_score(candidate: dict[str, Any]) -> tuple[int, list[str]]:
    signal = str(candidate.get("signal", "NO TRADE")).upper()
    if signal not in {"BUY CE", "BUY PE"}:
        return 0, ["NO_DIRECTION"]
    if candidate.get("market_data_fresh") is not True:
        return 0, ["STALE_MARKET_DATA"]
    if candidate.get("market_integrity_ok") is not True:
        return 0, ["MARKET_INTEGRITY_REJECTED"]
    if candidate.get("mtf_aligned") is not True:
        return 0, ["MTF_NOT_ALIGNED"]

    score = 0
    reasons: list[str] = []
    m15 = str(candidate.get("m15_trend", "MIXED")).upper()
    h1 = str(candidate.get("h1_trend", "MIXED")).upper()
    rsi = _num(candidate, "rsi")
    volume_ratio = _num(candidate, "volume_ratio")
    breakout = _num(candidate, "breakout_strength")
    body = _num(candidate, "body_strength")
    ema_gap = _num(candidate, "ema_gap_pct")
    rsi_slope = _num(candidate, "rsi_slope")
    atr_pct = _num(candidate, "atr_pct")

    directional = "BULLISH" if signal == "BUY CE" else "BEARISH"
    if m15 == directional and h1 == directional:
        score += 18; reasons.append("MTF_DIRECTION")
    if breakout >= 1.0:
        score += 18; reasons.append("BREAKOUT")
    elif breakout >= 0.6:
        score += 10; reasons.append("EARLY_BREAKOUT")
    if volume_ratio >= 1.5:
        score += 16; reasons.append("VOLUME_EXPANSION")
    elif volume_ratio >= 1.2:
        score += 9; reasons.append("VOLUME_CONFIRMATION")
    if body >= 0.60:
        score += 10; reasons.append("STRONG_CANDLE_BODY")
    elif body >= 0.40:
        score += 5; reasons.append("HEALTHY_CANDLE_BODY")
    if ema_gap >= 0.12:
        score += 10; reasons.append("EMA_ALIGNMENT")
    elif ema_gap >= 0.06:
        score += 5; reasons.append("EMA_ALIGNMENT_WEAK")

    if signal == "BUY CE" and 52 <= rsi <= 72 and rsi_slope > 0:
        score += 10; reasons.append("BULLISH_MOMENTUM")
    elif signal == "BUY PE" and 28 <= rsi <= 48 and rsi_slope < 0:
        score += 10; reasons.append("BEARISH_MOMENTUM")
    elif signal == "BUY CE" and rsi > 78:
        score -= 15; reasons.append("OVEREXTENDED_RSI")
    elif signal == "BUY PE" and rsi < 22:
        score -= 15; reasons.append("OVEREXTENDED_RSI")

    # Avoid dead markets where option premium decay/spread can dominate the move.
    if atr_pct < 0.08:
        score -= 12; reasons.append("LOW_REALIZED_RANGE")
    elif atr_pct >= 0.15:
        score += 4; reasons.append("ACTIVE_RANGE")

    return max(0, min(100, score)), reasons


def select_index_momentum_candidate(results: Iterable[dict[str, Any]], minimum_score: int = MIN_SCORE) -> dict[str, Any] | None:
    """Return the strongest validated index momentum candidate, if any."""
    candidates = []
    for candidate in results:
        if str(candidate.get("symbol", "")).upper() not in INDEX_SYMBOLS:
            continue
        momentum_score, reasons = _signal_score(candidate)
        candidate = dict(candidate)
        candidate["momentum_score"] = momentum_score
        candidate["momentum_reasons"] = reasons
        candidate["strategy"] = "INDEX_MOMENTUM_SCALP"
        if momentum_score >= minimum_score:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["momentum_score"], item.get("score", 0)))


def build_dynamic_exits(entry: float, atr: float, option_ltp: float) -> dict[str, float]:
    """Build conservative option-premium exits from underlying volatility.

    The premium cap and minimum stop distance prevent absurd exits when ATR is
    missing or unusually small. Targets are intentionally asymmetric to support
    fast momentum trades while preserving a defined loss before entry.
    """
    entry = float(entry)
    atr = max(float(atr or 0), 0.0)
    option_ltp = max(float(option_ltp or entry), 0.01)
    # Approximate option premium movement from normalized underlying range,
    # bounded so a single noisy ATR cannot create an unrealistic target.
    range_pct = min(max((atr / max(option_ltp, 1.0)), 0.08), 0.35)
    stop_pct = min(max(range_pct * 0.45, 0.08), 0.14)
    target1_pct = min(max(range_pct * 0.90, 0.12), 0.25)
    target2_pct = min(max(range_pct * 1.80, 0.22), 0.50)
    return {
        "stop_loss": round(entry * (1.0 - stop_pct), 2),
        "target1": round(entry * (1.0 + target1_pct), 2),
        "target2": round(entry * (1.0 + target2_pct), 2),
        "stop_pct": stop_pct,
        "target1_pct": target1_pct,
        "target2_pct": target2_pct,
    }
