from datetime import datetime, time as dt_time, timedelta

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
ENTRY_START = dt_time(9, 30)
LAST_ENTRY = dt_time(14, 45)


def is_weekday(now):
    return now.weekday() < 5


def in_entry_window(now):
    return is_weekday(now) and ENTRY_START <= now.time() <= LAST_ENTRY


def next_weekday_0915(now):
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now.time() >= MARKET_CLOSE or not is_weekday(now):
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate
