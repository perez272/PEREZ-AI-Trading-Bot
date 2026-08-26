from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

from src.options_surge_engine import OptionsSurgeEngine
from src.expiry_learning_engine import ExpiryLearningEngine


def snap(ts, ltp):
    return {
        "symbol": "NIFTY", "option_type": "CE", "instrument_key": "NFO|TEST",
        "observed_ts": ts.isoformat(),
        "market_data": {"ltp": ltp, "volume": 1000, "oi": 5000},
        "option_greeks": {"iv": 20},
    }


def test_surge_emits_5_10_15_minute_events():
    engine = OptionsSurgeEngine(threshold_pct=5, max_age_seconds=2000)
    now = datetime.now(timezone.utc)
    assert engine.observe(snap(now - timedelta(minutes=15), 100)) == []
    assert engine.observe(snap(now - timedelta(minutes=10), 100)) == []
    assert engine.observe(snap(now - timedelta(minutes=5), 100)) == []
    events = engine.observe(snap(now, 110))
    assert {e["window_minutes"] for e in events} == {5, 10, 15}
    assert all(e["current_ltp"] == 110 for e in events)


def test_expiry_learning_persists_events(tmp_path: Path):
    db = tmp_path / "expiry.sqlite3"
    engine = ExpiryLearningEngine(db)
    now = datetime.now(timezone.utc).isoformat()
    events = [{"type": "SURGE", "symbol": "NIFTY", "option_type": "CE", "instrument_key": "NFO|TEST", "window_minutes": w, "move_pct": 10, "current_ltp": 110, "observed_ts": now, "expiry": now} for w in (5, 10, 15)]
    assert engine.record_events(events) == 3
    assert engine.record_events(events) == 0
    stats = engine.stats()
    assert stats["events"] == 3
    assert stats["by_window"] == {5: 1, 10: 1, 15: 1}
