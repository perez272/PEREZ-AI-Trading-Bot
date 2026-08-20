import numpy as np

from src.indicators import calculate_indicators


def test_calculate_indicators_with_sample_candles():
    """Indicator calculation must be deterministic and must not call Angel One."""
    candles = []
    base_price = 100.0

    for index in range(250):
        price = base_price + index * 0.25
        candles.append(
            [
                f"2026-08-01 {9 + (index // 60):02d}:{(15 + index) % 60:02d}",
                price - 0.10,
                price + 0.50,
                price - 0.50,
                price,
                1000 + index,
            ]
        )

    df = calculate_indicators(candles)

    expected_columns = {
        "EMA20",
        "EMA50",
        "EMA200",
        "RSI",
        "MACD",
        "MACD_SIGNAL",
        "ATR",
        "VWAP",
    }

    assert expected_columns.issubset(df.columns)
    assert len(df) == 250
    assert df["EMA20"].iloc[-1] > 0
    assert df["EMA50"].iloc[-1] > 0
    assert df["EMA200"].iloc[-1] > 0
    assert np.isfinite(df["RSI"].iloc[-1])
    assert np.isfinite(df["MACD"].iloc[-1])
    assert np.isfinite(df["MACD_SIGNAL"].iloc[-1])
    assert np.isfinite(df["ATR"].iloc[-1])
    assert np.isfinite(df["VWAP"].iloc[-1])
