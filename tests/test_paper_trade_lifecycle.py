from datetime import datetime, timezone

from src.paper_trade_lifecycle import elapsed_seconds, now_ist, now_utc


def test_lifecycle_timestamps_are_timezone_aware():
    utc = now_utc()
    ist = now_ist()
    assert datetime.fromisoformat(utc).tzinfo is not None
    assert datetime.fromisoformat(ist).tzinfo is not None


def test_elapsed_seconds():
    start = "2026-09-16T03:45:21+00:00"
    end = "2026-09-16T03:45:22.250+00:00"
    assert elapsed_seconds(start, end) == 1.25
