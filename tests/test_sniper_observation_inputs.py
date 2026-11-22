from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.sniper_observation_inputs import build_underlying_context, option_volume_expansion

IST = ZoneInfo("Asia/Kolkata")


def _candles(start="2026-11-24T09:15:00+05:30", count=20, close_step=1.0):
    first = datetime.fromisoformat(start)
    rows = []
    for i in range(count):
        close = 25000 + i * close_step
        rows.append([(first + timedelta(minutes=i)).isoformat(),
                     close - 0.5, close + 1, close - 1, close, 1000])
    return rows


def test_underlying_context_derives_mtf_and_orb_from_completed_real_candles():
    candles = _candles()
    result = build_underlying_context(candles, "2026-11-24T09:35:30+05:30")
    assert result["underlying_input_status"] == "READY"
    assert result["orb_breakout"] is True
    assert result["breakout_direction"] == "CE"
    assert set(result["mtf_moves_pct"]) == {"1m", "3m", "5m"}
    assert all(value > 0 for value in result["mtf_moves_pct"].values())


def test_incomplete_opening_range_does_not_claim_orb():
    result = build_underlying_context(_candles(count=10),
                                     "2026-11-24T09:26:30+05:30")
    assert result["orb_breakout"] is False
    assert result["underlying_input_status"] == "INSUFFICIENT_OR_STALE"


def test_stale_underlying_candles_fail_closed():
    result = build_underlying_context(_candles(),
                                     "2026-11-24T10:00:00+05:30")
    assert result["underlying_input_status"] == "INSUFFICIENT_OR_STALE"
    assert result["breakout_direction"] is None


def test_option_volume_ratio_uses_interval_deltas_not_cumulative_total():
    start = datetime(2026, 11, 24, 10, 0, tzinfo=IST)
    points = [{"observed_at": (start + timedelta(minutes=i)).isoformat(),
               "volume": 1000 + i * (100 if i < 6 else 300)}
              for i in range(7)]
    result = option_volume_expansion(points, minimum_baseline_intervals=5)
    assert result["status"] == "READY"
    assert result["volume_ratio"] == 3.0


def test_option_volume_gap_or_reset_fails_closed():
    points = [
        {"observed_at": "2026-11-24T10:00:00+05:30", "volume": 100},
        {"observed_at": "2026-11-24T10:01:00+05:30", "volume": 200},
        {"observed_at": "2026-11-24T10:05:00+05:30", "volume": 300},
    ]
    assert option_volume_expansion(points)["status"] == "INSUFFICIENT_VOLUME_HISTORY"
