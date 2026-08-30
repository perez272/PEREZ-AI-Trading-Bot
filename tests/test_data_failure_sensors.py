from datetime import datetime, timedelta, timezone
from src.data_failure_sensors import PipelineSensor

def test_empty_stage_is_failure():
    s = PipelineSensor(); s.record("market_snapshot", rows=0, valid=False)
    assert s.snapshot()["healthy"] is False

def test_stale_data_is_failure():
    s = PipelineSensor(max_age_seconds=300); now = datetime.now(timezone.utc)
    assert s.check_freshness(now - timedelta(seconds=301), now)["healthy"] is False

def test_gap_is_failure():
    s = PipelineSensor(expected_interval_seconds=60); now = datetime.now(timezone.utc)
    assert s.check_continuity(now - timedelta(seconds=151), now)["healthy"] is False

def test_fresh_data_is_healthy():
    s = PipelineSensor(max_age_seconds=300); now = datetime.now(timezone.utc)
    s.record("decision_input", rows=1, valid=True)
    assert s.check_freshness(now - timedelta(seconds=10), now)["healthy"] is True
    assert s.snapshot()["healthy"] is True
