import pandas as pd
import pandas_ta as ta

def calculate_indicators(candles):
    df = pd.DataFrame(
        candles,
        columns=["time","open","high","low","close","volume"]
    )

    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time")
    df.set_index("time", inplace=True)

    cols = ["open","high","low","close","volume"]
    df[cols] = df[cols].astype(float)

    df["EMA20"] = ta.ema(df["close"], length=20)
    df["EMA50"] = ta.ema(df["close"], length=50)
    df["EMA200"] = ta.ema(df["close"], length=200)

    df["RSI"] = ta.rsi(df["close"], length=14)

    macd = ta.macd(df["close"])
    df["MACD"] = macd["MACD_12_26_9"]
    df["MACD_SIGNAL"] = macd["MACDs_12_26_9"]

    df["VWAP"] = ta.vwap(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        volume=df["volume"]
    )

    return df
