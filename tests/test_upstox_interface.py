from datetime import datetime

from src import upstox_market_data as upstox


def test_upstox_builtin_index_mapping_survives_missing_env(monkeypatch):
    monkeypatch.delenv("UPSTOX_INSTRUMENT_KEYS_JSON", raising=False)
    keys = upstox.instrument_keys()
    assert keys["NIFTY"] == "NSE_INDEX|Nifty 50"
    assert keys["BANKNIFTY"] == "NSE_INDEX|Nifty Bank"


def test_get_historical_candles_merges_historical_and_intraday(monkeypatch):
    historical = [
        ["2026-08-31T10:00:00+05:30", 100, 101, 99, 100.5, 1000, 0],
        ["2026-08-31T10:05:00+05:30", 100.5, 102, 100, 101.5, 1200, 0],
    ]
    intraday = [
        ["2026-08-31T10:05:00+05:30", 100.5, 102.2, 100.2, 101.8, 1300, 0],
        ["2026-08-31T10:10:00+05:30", 101.8, 103, 101.5, 102.7, 1400, 0],
    ]

    monkeypatch.setattr(upstox, "_get", lambda path, params=None: {"status": "success", "data": {"candles": historical}})
    monkeypatch.setattr(upstox, "get_intraday_candles", lambda instrument_key, interval_minutes=5: upstox._normalize_candles(intraday))
    monkeypatch.setattr(upstox, "instrument_keys", lambda: {"NIFTY": "NSE_INDEX|Nifty 50"})

    candles = upstox.get_historical_candles("NIFTY", 5, lookback_days=15)

    assert len(candles) == 3
    assert candles[-2][4] == 101.8
    assert len(candles[-1]) == 6


def test_snapshot_reports_age_from_candle_close(monkeypatch):
    candle_start = datetime.now(upstox.IST).replace(second=0, microsecond=0)
    candle_start = candle_start.replace(minute=(candle_start.minute // 5) * 5)
    monkeypatch.setattr(upstox, "instrument_keys", lambda: {"NIFTY": "NSE_INDEX|Nifty 50"})
    monkeypatch.setattr(upstox, "get_latest_closed_candle", lambda instrument_key, interval_minutes=5: [candle_start.isoformat(), 100, 101, 99, 100.5, 1000])
    monkeypatch.setattr(upstox, "get_ltp", lambda instrument_key: 100.7)

    snapshot = upstox.get_snapshot("NIFTY")

    assert snapshot["closed_5m_close"] == 100.5
    assert snapshot["ltp"] == 100.7
    assert snapshot["candle_age_seconds"] < 360
