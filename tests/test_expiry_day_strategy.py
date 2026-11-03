from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.expiry_day_strategy import evaluate_nifty_expiry_setup, is_expiry_session

IST = ZoneInfo("Asia/Kolkata")


def _candles():
    # 60 completed 5-minute bars, arranged into complete 15-minute groups.
    start = datetime(2026, 11, 2, 9, 0, tzinfo=IST)
    rows = []
    price = 23000.0
    for i in range(60):
        stamp = start + timedelta(minutes=5 * i)
        # A steady bullish trend with the final 15-minute candle breaking
        # above the preceding 15-minute high.
        open_price = price
        price += 2.0
        high = price + 0.2
        low = open_price - 0.1
        close = price
        volume = 2000.0 if i < 59 else 4000.0
        rows.append([stamp.isoformat(), open_price, high, low, close, volume])
    return rows


def test_expiry_session_accepts_expiry_day_and_preceding_weekday():
    now = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    assert is_expiry_session("2026-11-03", now)
    assert is_expiry_session("2026-11-04", now)
    assert not is_expiry_session("2026-11-10", now)


def test_rejects_non_nifty_and_outside_entry_window():
    now = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    args = dict(
        candles=_candles(), option_type="CE", expiry="2026-11-03",
        strike=23000, option_move_1m_pct=2, option_move_3m_pct=3,
        option_move_5m_pct=5, spread_pct=0.2, option_volume=1000,
        option_oi=10000, now=now,
    )
    assert "NIFTY_ONLY" in evaluate_nifty_expiry_setup(symbol="BANKNIFTY", **args)["reasons"]
    late = evaluate_nifty_expiry_setup(symbol="NIFTY", **{**args, "now": datetime(2026, 11, 3, 14, 31, tzinfo=IST)})
    assert "OUTSIDE_EXPIRY_ENTRY_WINDOW" in late["reasons"]


def test_requires_positive_option_premium_confirmation_and_liquidity():
    now = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    result = evaluate_nifty_expiry_setup(
        _candles(), symbol="NIFTY", option_type="CE", expiry="2026-11-03",
        strike=23000, option_move_1m_pct=-0.1, option_move_3m_pct=1,
        option_move_5m_pct=5, spread_pct=0.2, option_volume=0, option_oi=10000,
        now=now,
    )
    assert "OPTION_PREMIUM_NOT_CONFIRMED" in result["reasons"]
    assert "NO_OPTION_VOLUME" in result["reasons"]


def test_fails_closed_for_insufficient_history():
    now = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    result = evaluate_nifty_expiry_setup(
        _candles()[:20], symbol="NIFTY", option_type="CE", expiry="2026-11-03",
        strike=23000, option_move_1m_pct=2, option_move_3m_pct=3,
        option_move_5m_pct=5, spread_pct=0.2, option_volume=1000, option_oi=10000,
        now=now,
    )
    assert not result["eligible"]
    assert "INSUFFICIENT_COMPLETED_5M_HISTORY" in result["reasons"]
