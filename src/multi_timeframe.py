"""Multi-timeframe confirmation built from the same fresh broker candle set.

No extra broker requests are made: the scanner's 5-minute candles are
resampled locally into 15-minute and 60-minute bars. Indicator calculations
use pandas-only operations so scanner behavior does not depend on pandas-ta
compatibility.
"""

import pandas as pd


def _ema(series, span):
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss.ne(0), 100.0)
    rsi = rsi.where(avg_gain.ne(0), 0.0)
    return rsi


def _frame(candles, rule):
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").set_index("time")
    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def _trend_score(df):
    if len(df) < 25:
        return 0, "INSUFFICIENT"
    close_series = df["close"]
    ema20_series = _ema(close_series, 20)
    ema50_series = _ema(close_series, 50)
    rsi_series = _rsi(close_series, 14)
    ema20 = ema20_series.iloc[-1]
    ema50 = ema50_series.iloc[-1]
    rsi = rsi_series.iloc[-1]
    close = float(close_series.iloc[-1])
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
        alignment = s15 + s60
        if alignment == 2:
            return {"m15": t15, "h1": t60, "direction": "BULLISH", "quality": 10, "aligned": True}
        if alignment == -2:
            return {"m15": t15, "h1": t60, "direction": "BEARISH", "quality": 10, "aligned": True}
        return {"m15": t15, "h1": t60, "direction": "MIXED", "quality": -10, "aligned": False}
    except (TypeError, ValueError, KeyError, IndexError):
        return {"m15": "ERROR", "h1": "ERROR", "direction": "UNKNOWN", "quality": -20, "aligned": False}
