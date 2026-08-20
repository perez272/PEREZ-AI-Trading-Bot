"""PEREZ PRO multi-factor market intelligence engine.

The engine is deterministic and fail-closed: missing/invalid market evidence
cannot become a bullish or bearish signal.  It combines a fast execution
frame with higher-timeframe confirmation before admitting a trade candidate.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _safe(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if pd.notna(value) else default
    except (TypeError, ValueError):
        return default


def data_quality_gate(df: pd.DataFrame, min_rows: int = 30) -> tuple[bool, list[str]]:
    """Reject structurally unsafe data before technical scoring."""
    if df is None or len(df) < min_rows:
        return False, ["INSUFFICIENT_ROWS"]
    required = ["open", "high", "low", "close", "volume", "EMA20", "EMA50", "EMA200", "RSI", "MACD", "MACD_SIGNAL", "ATR", "VWAP"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return False, [f"MISSING:{c}" for c in missing]
    tail = df.tail(20)
    numeric = tail[required].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        return False, ["NAN_IN_DECISION_WINDOW"]
    if (tail["volume"] < 0).any():
        return False, ["NEGATIVE_VOLUME"]
    if (tail["high"] < tail[["open", "close"]].max(axis=1)).any():
        return False, ["HIGH_BELOW_BODY"]
    if (tail["low"] > tail[["open", "close"]].min(axis=1)).any():
        return False, ["LOW_ABOVE_BODY"]
    if (tail["high"] < tail["low"]).any():
        return False, ["HIGH_BELOW_LOW"]
    if (tail["close"] <= 0).any():
        return False, ["NON_POSITIVE_CLOSE"]
    if (tail["ATR"] < 0).any():
        return False, ["INVALID_ATR"]
    return True, []


def _direction_score(df: pd.DataFrame) -> tuple[float, float]:
    last = df.iloc[-1]
    bull = bear = 0.0
    close = _safe(last["close"])
    for fast, slow, weight in (("EMA20", "EMA50", 10), ("EMA50", "EMA200", 10)):
        if _safe(last[fast]) > _safe(last[slow]):
            bull += weight
        else:
            bear += weight
    if close > _safe(last["VWAP"]):
        bull += 8
    elif close < _safe(last["VWAP"]):
        bear += 8
    if _safe(last["MACD"]) > _safe(last["MACD_SIGNAL"]):
        bull += 8
    else:
        bear += 8
    rsi = _safe(last["RSI"], 50)
    if 55 <= rsi <= 72:
        bull += 7
    elif 28 <= rsi <= 45:
        bear += 7
    elif rsi > 78:
        bear += 4
    elif rsi < 22:
        bull += 4
    return bull, bear


def _participation(df: pd.DataFrame) -> tuple[float, float, float]:
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    baseline = vol.rolling(20, min_periods=5).mean()
    ratio = _safe((vol.iloc[-1] / baseline.iloc[-1]) if baseline.iloc[-1] else 0)
    last = df.iloc[-1]
    spread = max(_safe(last["high"]) - _safe(last["low"]), 0.0)
    body = abs(_safe(last["close"]) - _safe(last["open"]))
    body_ratio = body / spread if spread else 0.0
    bull = bear = 0.0
    if ratio >= 1.5:
        if _safe(last["close"]) >= _safe(last["open"]):
            bull += 12 * min(ratio / 2.0, 1.5)
        else:
            bear += 12 * min(ratio / 2.0, 1.5)
    elif ratio >= 1.15:
        if _safe(last["close"]) >= _safe(last["open"]):
            bull += 5
        else:
            bear += 5
    if body_ratio >= 0.65:
        if _safe(last["close"]) > _safe(last["open"]):
            bull += 5
        else:
            bear += 5
    return ratio, bull, bear


def _structure(df: pd.DataFrame) -> tuple[float, float, str]:
    if len(df) < 12:
        return 0.0, 0.0, "INSUFFICIENT"
    recent = df.tail(12)
    prior = df.iloc[:-2].tail(10)
    last = df.iloc[-1]
    resistance = _safe(prior["high"].max())
    support = _safe(prior["low"].min())
    close = _safe(last["close"])
    bull = bear = 0.0
    label = "RANGE"
    if resistance and close > resistance:
        bull += 15; label = "BULL_BREAKOUT"
    elif support and close < support:
        bear += 15; label = "BEAR_BREAKDOWN"
    else:
        highs = recent["high"].tail(5).mean() - recent["high"].head(5).mean()
        lows = recent["low"].tail(5).mean() - recent["low"].head(5).mean()
        if highs > 0 and lows > 0:
            bull += 7; label = "HIGHER_HIGH_LOW"
        elif highs < 0 and lows < 0:
            bear += 7; label = "LOWER_HIGH_LOW"
    return bull, bear, label


def _regime(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    close = _safe(last["close"])
    ema20, ema50, ema200 = _safe(last["EMA20"]), _safe(last["EMA50"]), _safe(last["EMA200"])
    atr = _safe(last.get("ATR"))
    volatility = atr / close if close else 0
    if ema20 > ema50 > ema200 and close > ema20:
        return "BULL_TREND_HIGH_VOL" if volatility > 0.015 else "BULL_TREND"
    if ema20 < ema50 < ema200 and close < ema20:
        return "BEAR_TREND_HIGH_VOL" if volatility > 0.015 else "BEAR_TREND"
    return "RANGE_HIGH_VOL" if volatility > 0.015 else "RANGE"


def _external_evidence(context: Mapping[str, Any] | None) -> tuple[float, float, list[str]]:
    context = context or {}
    bull = bear = 0.0
    notes: list[str] = []
    for key, bull_points, bear_points, bull_note, bear_note in (
        ("news_bias", 8, 8, "NEWS_BULLISH", "NEWS_BEARISH"),
        ("oi_bias", 8, 8, "OI_BULLISH", "OI_BEARISH"),
        ("market_regime", 5, 5, "MARKET_BULLISH", "MARKET_BEARISH"),
    ):
        value = str(context.get(key, "neutral")).lower()
        if value == "bullish":
            bull += bull_points; notes.append(bull_note)
        elif value == "bearish":
            bear += bear_points; notes.append(bear_note)
    return bull, bear, notes


def evaluate(df: pd.DataFrame, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if df is None or len(df) < 30:
        return {"score": 0, "direction": "NO_TRADE", "regime": "INSUFFICIENT", "reasons": ["INSUFFICIENT_DATA"]}
    ok, quality_reasons = data_quality_gate(df)
    if not ok:
        return {"score": 0, "direction": "NO_TRADE", "regime": "INVALID_DATA", "reasons": quality_reasons, "data_quality": False}
    bull_t, bear_t = _direction_score(df)
    volume_ratio, bull_v, bear_v = _participation(df)
    bull_s, bear_s, structure = _structure(df)
    bull_e, bear_e, notes = _external_evidence(context)
    bull = bull_t + bull_v + bull_s + bull_e
    bear = bear_t + bear_v + bear_s + bear_e
    total = bull + bear
    conviction = _clip(50 + (bull - bear) / max(total, 1) * 50)
    direction = "BUY CE" if conviction >= 65 else "BUY PE" if conviction <= 35 else "NO_TRADE"
    return {"score": round(conviction, 2), "direction": direction, "bullish_points": round(bull, 2), "bearish_points": round(bear, 2), "volume_ratio": round(volume_ratio, 2), "structure": structure, "regime": _regime(df), "reasons": notes, "data_quality": True}


def evaluate_multi_timeframe(frames: Mapping[str, pd.DataFrame], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Require aligned 5m/15m/60m evidence; 5m drives entry, higher frames confirm."""
    required = ("5m", "15m", "60m")
    missing = [tf for tf in required if tf not in frames]
    if missing:
        return {"score": 0, "direction": "NO_TRADE", "decision": "REJECT", "reasons": [f"MISSING_TIMEFRAME:{tf}" for tf in missing]}
    decisions = {tf: evaluate(frames[tf], context) for tf in required}
    bad = [tf for tf, d in decisions.items() if not d.get("data_quality")]
    if bad:
        return {"score": 0, "direction": "NO_TRADE", "decision": "REJECT", "reasons": [f"BAD_DATA:{tf}" for tf in bad], "timeframes": decisions}
    directions = {tf: d["direction"] for tf, d in decisions.items()}
    five = decisions["5m"]
    higher = [decisions["15m"], decisions["60m"]]
    bull_confirm = all(d["direction"] == "BUY CE" for d in higher)
    bear_confirm = all(d["direction"] == "BUY PE" for d in higher)
    if five["direction"] == "BUY CE" and bull_confirm:
        direction = "BUY CE"
    elif five["direction"] == "BUY PE" and bear_confirm:
        direction = "BUY PE"
    else:
        return {"score": round(five["score"], 2), "direction": "NO_TRADE", "decision": "REJECT", "reasons": ["MTF_NOT_ALIGNED"], "timeframes": decisions, "directions": directions}
    score = round((five["score"] * 0.50) + (decisions["15m"]["score"] * 0.30) + (decisions["60m"]["score"] * 0.20), 2)
    return {"score": score, "direction": direction, "decision": "ADMIT" if score >= 65 else "REJECT", "reasons": ["MTF_ALIGNED"], "timeframes": decisions, "directions": directions, "data_quality": True}
