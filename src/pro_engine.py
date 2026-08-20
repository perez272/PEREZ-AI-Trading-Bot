"""PEREZ PRO multi-factor market intelligence engine.

Pure pandas/numpy-style calculations only: no extra dependency and no fake
news/OI/Greeks data. External evidence can be supplied through ``context``.
Missing external evidence is neutral or fail-closed rather than invented.
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


def _direction_score(df: pd.DataFrame) -> tuple[float, float]:
    """Return bullish/bearish technical structure scores."""
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
    """Volume participation: ratio, bullish points, bearish points."""
    d = df.copy()
    vol = pd.to_numeric(d["volume"], errors="coerce").fillna(0)
    baseline = vol.rolling(20, min_periods=5).mean()
    ratio = _safe((vol.iloc[-1] / baseline.iloc[-1]) if baseline.iloc[-1] else 0)
    last = d.iloc[-1]
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
    """Detect recent swing structure and breakout pressure."""
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
        bull += 15
        label = "BULL_BREAKOUT"
    elif support and close < support:
        bear += 15
        label = "BEAR_BREAKDOWN"
    else:
        highs = recent["high"].tail(5).mean() - recent["high"].head(5).mean()
        lows = recent["low"].tail(5).mean() - recent["low"].head(5).mean()
        if highs > 0 and lows > 0:
            bull += 7
            label = "HIGHER_HIGH_LOW"
        elif highs < 0 and lows < 0:
            bear += 7
            label = "LOWER_HIGH_LOW"
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
    """Apply only supplied trusted external evidence; never fabricate it."""
    context = context or {}
    bull = bear = 0.0
    notes: list[str] = []
    news = str(context.get("news_bias", "neutral")).lower()
    if news == "bullish":
        bull += 8; notes.append("NEWS_BULLISH")
    elif news == "bearish":
        bear += 8; notes.append("NEWS_BEARISH")
    oi = str(context.get("oi_bias", "neutral")).lower()
    if oi == "bullish":
        bull += 8; notes.append("OI_BULLISH")
    elif oi == "bearish":
        bear += 8; notes.append("OI_BEARISH")
    market = str(context.get("market_regime", "neutral")).lower()
    if market == "bullish":
        bull += 5; notes.append("MARKET_CONFIRMED")
    elif market == "bearish":
        bear += 5; notes.append("MARKET_CONFIRMED")
    return bull, bear, notes


def evaluate(df: pd.DataFrame, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Produce a transparent 0-100 directional conviction score."""
    if df is None or len(df) < 30:
        return {"score": 0, "direction": "NO_TRADE", "regime": "INSUFFICIENT", "reasons": ["INSUFFICIENT_DATA"]}
    bull_t, bear_t = _direction_score(df)
    volume_ratio, bull_v, bear_v = _participation(df)
    bull_s, bear_s, structure = _structure(df)
    bull_e, bear_e, notes = _external_evidence(context)
    bull = bull_t + bull_v + bull_s + bull_e
    bear = bear_t + bear_v + bear_s + bear_e
    total = bull + bear
    conviction = _clip(50 + (bull - bear) / max(total, 1) * 50)
    direction = "BUY CE" if conviction >= 65 else "BUY PE" if conviction <= 35 else "NO_TRADE"
    return {
        "score": round(conviction, 2),
        "direction": direction,
        "bullish_points": round(bull, 2),
        "bearish_points": round(bear, 2),
        "volume_ratio": round(volume_ratio, 2),
        "structure": structure,
        "regime": _regime(df),
        "reasons": notes,
    }
