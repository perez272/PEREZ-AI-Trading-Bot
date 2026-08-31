from datetime import datetime, timedelta, timezone

from src.explosive_move_detector import detect_explosive_move

BASE = datetime(2026, 8, 31, 9, 30, tzinfo=timezone.utc)


def _snap(ltp, minutes=0, volume=1000, bid=None, ask=None):
    return {
        "instrument_key": "TEST|1",
        "observed_ts": (BASE + timedelta(minutes=minutes)).isoformat(),
        "market_data": {
            "ltp": ltp,
            "volume": volume,
            "bid_price": bid if bid is not None else ltp - 0.05,
            "ask_price": ask if ask is not None else ltp + 0.05,
        },
    }


def test_detects_early_acceleration_before_large_move():
    history = [_snap(100, 0, 1000), _snap(101, 1, 1100), _snap(102, 2, 1200), _snap(103, 3, 1400), _snap(104, 4, 1600)]
    signal = detect_explosive_move("NIFTY", "CE", _snap(108, 5, 3000), history)
    assert signal is not None
    assert signal.early is True
    assert signal.score >= 55
    assert "accelerating_velocity" in signal.reasons


def test_does_not_signal_without_history():
    assert detect_explosive_move("NIFTY", "CE", _snap(105, 5), []) is None


def test_wide_spread_is_penalized():
    history = [_snap(100, 0), _snap(101, 1), _snap(102, 2), _snap(103, 3), _snap(104, 4)]
    # Use a spread that is unambiguously above the detector's 5% threshold.
    signal = detect_explosive_move("NIFTY", "CE", _snap(106, 5, 3000, 5, 11), history)
    assert signal is not None
    assert signal.spread_pct > 5
    assert "wide_spread_penalty" in signal.reasons
