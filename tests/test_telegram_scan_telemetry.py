from src.live_telegram_updater import _scan_message


def test_scan_message_includes_persisted_pipeline_metrics():
    heartbeat = {
        "status": "scanned",
        "timestamp_utc": "2026-08-25T03:50:00+00:00",
        "candidates": 3,
        "capital": 50000.0,
        "market_data_api_attempts": 6,
        "market_data_live_refreshes": 4,
        "market_data_cache_hits": 2,
        "market_data_fresh_candles": 6,
        "market_data_fresh_to_decision": 5,
        "decision_evaluations": 5,
        "market_data_blocked_or_failed": 0,
        "market_data_invalid_or_stale": 1,
    }
    message = _scan_message(heartbeat)
    assert "DEEP SCAN TELEMETRY" in message
    assert "Candidates after scan: 3" in message
    assert "API attempts: 6" in message
    assert "Fresh → decision engine: 5" in message
    assert "Invalid/stale data: 1" in message


def test_scan_message_is_safe_when_heartbeat_missing():
    message = _scan_message({})
    assert "No heartbeat scan telemetry persisted yet." in message
    assert "does not alter trading or risk decisions" in message
