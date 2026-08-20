"""Multi-timeframe confirmation built from the same fresh broker candle set.

No extra broker requests are made: the scanner's 5-minute candles are
resampled locally into 15-minute and 60-minute bars. This reduces API load
while making entries require alignment across short, medium and regime
trend.
"""

import pandas as pd
import pandas_ta as ta


def _frame(candles, rule):
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").set_index("time")
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    out = df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()
    return out


def _trend_score(df):
    if len(df) < 25:
        return 0, "INSUFFICIENT"
    ema20 = ta.ema(df["close"], length=20).iloc[-1]
    ema50 = ta.ema(df["close"], length=50).iloc[-1]
    rsi = ta.rsi(df["close"], length=14).iloc[-1]
    close = float(df["close"].iloc[-1])
    if pd.isna(ema20) or pd.isna(ema50) or pd.isna(rsi):
        return 0, "INSUFFICIENT"
    if close > ema20 > ema50 and rsi >= 52:
        return 1, "BULLISH"
    if close < ema20 < ema50 and rsi <= 48:
        return -1, "BEARISH"
    return 0, "NEUTRAL"


def confirm(candles):
    """Return directional confirmation and a bounded quality adjustment."""
    try:
        m15 = _frame(candles, "15min")
        h1 = _frame(candles, "60min")
        s15, t15 = _trend_score(m15)
        s60, t60 = _trend_score(h1)
        # Higher timeframe has greater weight. Both aligned is preferred;
        # disagreement is a hard rejection at candidate-selection time.
        alignment = s15 + s60
        if alignment == 2:
            return {"m15": t15, "h1": t60, "direction": "BULLISH", "quality": 10, "aligned": True}
        if alignment == -2:
            return {"m15": t15, "h1": t60, "direction": "BEARISH", "quality": 10, "aligned": True}
        return {"m15": t15, "h1": t60, "direction": "MIXED", "quality": -10, "aligned": False}
    except (TypeError, ValueError, KeyError, IndexError):
        return {"m15": "ERROR", "h1": "ERROR", "direction": "UNKNOWN", "quality": -20, "aligned": False}
