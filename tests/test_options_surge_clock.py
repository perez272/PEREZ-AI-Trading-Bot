from datetime import datetime, timedelta, timezone

from src.options_surge_engine import OptionsSurgeEngine


def test_surge_detects_5_10_15_with_deterministic_clock():
    now = datetime(2026, 8, 26, 6, 15, tzinfo=timezone.utc)
    engine = OptionsSurgeEngine(clock=lambda: now, max_age_seconds=120)

    def snapshot(ts, price):
        return {
            "symbol": "NIFTY",
            "option_type": "CE",
            "instrument_key": "TEST|NIFTY|CE",
            "market_data": {"ltp": price, "volume": 1000, "oi": 5000},
            "observed_ts": ts.isoformat(),
        }

    for minutes, price in ((15, 100), (10, 100), (5, 100), (0, 110)):
        events = engine.observe(snapshot(now - timedelta(minutes=minutes), price))

    assert {e["window_minutes"] for e in events} == {5, 10, 15}
    assert all(e["move_pct"] == 10.0 for e in events)


def test_surge_rejects_stale_snapshot():
    now = datetime(2026, 8, 26, 6, 15, tzinfo=timezone.utc)
    engine = OptionsSurgeEngine(clock=lambda: now, max_age_seconds=120)
    stale = now - timedelta(minutes=3)
    snapshot = {
        "symbol": "NIFTY",
        "option_type": "CE",
        "instrument_key": "TEST|NIFTY|CE",
        "market_data": {"ltp": 110},
        "observed_ts": stale.isoformat(),
    }
    assert engine.observe(snapshot) == []
