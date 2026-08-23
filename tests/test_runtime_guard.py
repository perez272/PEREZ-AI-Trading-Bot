from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.session_clock import in_entry_window, next_weekday_0915


IST = ZoneInfo("Asia/Kolkata")


def test_entry_window_rejects_weekends():
    saturday = datetime(2026, 8, 22, 11, 0, tzinfo=IST)
    assert not in_entry_window(saturday)


def test_entry_window_accepts_weekday_entry_time():
    monday = datetime(2026, 8, 24, 10, 0, tzinfo=IST)
    assert in_entry_window(monday)


def test_entry_window_rejects_after_last_entry():
    monday = datetime(2026, 8, 24, 14, 46, tzinfo=IST)
    assert not in_entry_window(monday)


def test_next_session_skips_weekend():
    friday_after_close = datetime(2026, 8, 21, 16, 0, tzinfo=IST)
    target = next_weekday_0915(friday_after_close)
    assert target.weekday() == 0
    assert target.time() == time(9, 15)
