import pandas as pd

from src.multi_timeframe import confirm


def _candles(direction="up"):
    start = pd.Timestamp("2026-08-20 09:15")
    rows = []
    price = 100.0
    for i in range(360):
        if direction == "up":
            price += 0.20
        else:
            price -= 0.20
        ts = start + pd.Timedelta(minutes=5 * i)
        rows.append([ts.isoformat(), price - 0.1, price + 0.2, price - 0.2, price, 1000])
    return rows


def test_multi_timeframe_bullish_alignment():
    result = confirm(_candles("up"))
    assert result["aligned"] is True
    assert result["direction"] == "BULLISH"
    assert result["quality"] == 10


def test_multi_timeframe_bearish_alignment():
    result = confirm(_candles("down"))
    assert result["aligned"] is True
    assert result["direction"] == "BEARISH"
    assert result["quality"] == 10
