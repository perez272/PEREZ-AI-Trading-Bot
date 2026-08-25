from src.live_telegram_updater import _scan_message


def test_scan_message_includes_persisted_pipeline_metrics(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    monkeypatch.setenv("UPSTOX_ENABLED", "true")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "test-token")
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
        "upstox_fallback_attempts": 2,
        "upstox_fallback_successes": 2,
    }
    message = _scan_message(heartbeat)
    assert "DEEP SCAN TELEMETRY" in message
    assert "Candidates after scan: 3" in message
    assert "API attempts: 6" in message
    assert "Fresh → decision engine: 5" in message
    assert "Invalid/stale data: 1" in message
    assert "Upstox fallback attempts: 2" in message
    assert "Upstox credentials configured: YES" in message


def test_scan_message_is_safe_when_heartbeat_missing(monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    message = _scan_message({})
    assert "No heartbeat scan telemetry persisted yet." in message
    assert "does not alter trading or risk decisions" in message


def test_scan_message_marks_fail_closed_when_no_fresh_data_reached_decision(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    monkeypatch.setenv("UPSTOX_ENABLED", "true")
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    heartbeat = {
        "status": "scanned",
        "market_data_api_attempts": 5,
        "market_data_fresh_to_decision": 0,
        "market_data_blocked_or_failed": 5,
    }
    message = _scan_message(heartbeat)
    assert "FAIL-CLOSED MARKET DATA" in message
    assert "No fresh provider data reached the decision engine" in message
    assert "No trade decision was allowed" in message
    assert "Upstox credentials configured: NO" in message
