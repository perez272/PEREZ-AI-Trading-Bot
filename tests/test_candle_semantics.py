from datetime import datetime

from src.market_scanner import _bucket_start, _closed_candle_bucket, _normalize_closed_candles


class FrozenDateTime(datetime):
    current = datetime(2026, 8, 28, 10, 22, tzinfo=None)


def test_upstox_descending_candles_are_sorted_and_current_open_bucket_is_excluded(monkeypatch):
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    # 10:15 is open at 10:17 for a five-minute candle; 10:10 is the
    # most-recent closed candle and should be the newest accepted bucket.
    now = datetime(2026, 8, 28, 10, 17, tzinfo=ist)
    monkeypatch.setattr("src.market_scanner.datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: now),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))

    candles = [
        ["2026-08-28T10:15:00+05:30", 100, 101, 99, 100, 0, 0],  # still open at 10:17
        ["2026-08-28T10:10:00+05:30", 99, 100, 98, 99.5, 0, 0],
        ["2026-08-28T10:05:00+05:30", 98, 99, 97, 98.5, 0, 0],
    ]

    normalized = _normalize_closed_candles(candles, "NIFTY")

    assert normalized is not None
    assert [row[0] for row in normalized] == [
        "2026-08-28T10:05:00+05:30",
        "2026-08-28T10:10:00+05:30",
    ]
    assert _bucket_start(datetime.fromisoformat(normalized[-1][0])) == _closed_candle_bucket(now)


def test_exact_boundary_accepts_just_closed_five_minute_candle(monkeypatch):
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 8, 28, 10, 20, tzinfo=ist)
    monkeypatch.setattr("src.market_scanner.datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: now),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))

    candles = [["2026-08-28T10:15:00+05:30", 100, 101, 99, 100.5, 0, 0]]
    normalized = _normalize_closed_candles(candles, "NIFTY")

    assert normalized == candles
