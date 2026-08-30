from datetime import datetime, timedelta, timezone

from src.data_failure_sensors import PipelineSensor


def test_sensor_rejects_empty_stage():
    sensor = PipelineSensor()
    sensor.record("market_snapshot", rows=0, source="test", valid=False)
    state = sensor.snapshot()
    assert state["healthy"] is False
    assert state["failure_count"] == 1


def test_sensor_detects_stale_data():
    sensor = PipelineSensor(max_age_seconds=300)
    now = datetime.now(timezone.utc)
    result = sensor.check_freshness(now - timedelta(seconds=301), now)
    assert result["healthy"] is False


def test_sensor_detects_pipeline_gap():
    sensor = PipelineSensor(expected_interval_seconds=60)
    now = datetime.now(timezone.utc)
    result = sensor.check_continuity(now - timedelta(seconds=151), now)
    assert result["healthy"] is False


def test_sensor_accepts_healthy_stage_and_fresh_data():
    sensor = PipelineSensor(max_age_seconds=300, expected_interval_seconds=60)
    now = datetime.now(timezone.utc)
    sensor.record("decision_input", rows=4, source="existing_market_data", valid=True, timestamp=now)
    assert sensor.check_freshness(now - timedelta(seconds=10), now)["healthy"] is True
    assert sensor.snapshot()["healthy"] is True
