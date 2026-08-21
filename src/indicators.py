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
    # A continuously rising series has RSI 100; a continuously falling series 0.
    rsi = rsi.where(avg_loss.ne(0), 100.0)
    rsi = rsi.where(avg_gain.ne(0), 0.0)
    return rsi


def calculate_indicators(candles):
    """Calculate scanner indicators using pandas-only implementations.

    This intentionally avoids pandas-ta because the installed pandas/pandas-ta
    combination can return None for indicator calculations, which previously
    caused downstream `.iloc` crashes in the scanner.
    """
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=["time", "open", "high", "low", "close", "volume"],
    )

    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time")
    df.set_index("time", inplace=True)

    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return df

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"].fillna(0)

    df["EMA20"] = _ema(close, 20)
    df["EMA50"] = _ema(close, 50)
    df["EMA200"] = _ema(close, 200)
    df["RSI"] = _rsi(close, 14)

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = _ema(df["MACD"], 9)

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    typical_price = (high + low + close) / 3.0
    cumulative_volume = volume.cumsum()
    df["VWAP"] = (typical_price * volume).cumsum() / cumulative_volume.replace(0, float("nan"))

    return df
