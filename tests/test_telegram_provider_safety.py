import json


def test_telegram_status_deduplicates_unchanged_state(tmp_path, monkeypatch):
    import src.live_telegram_updater as updater

    updater.CHAT_ID = "test-chat"
    updater.HEARTBEAT_PATH = tmp_path / "heartbeat.json"
    updater.TELEGRAM_FINGERPRINT_PATH = tmp_path / "telegram_status_fingerprint.json"
    updater._save_fingerprint("")

    learning = {
        "completed_paper_trades": 0,
        "wins": 0,
        "learned_win_rate": 0.0,
        "learned_pnl": 0.0,
        "observations": 10,
        "rejections": 0,
        "lessons_events": 0,
        "option_surge_events": 0,
        "outcome_learning": "WAITING_FOR_FIRST_CLOSED_TRADE",
        "pattern_learning": "READY",
        "last_observation": "2026-08-25T18:00:00+00:00",
        "last_events": [],
    }
    monkeypatch.setattr(updater, "get_learning_status", lambda: learning)
    monkeypatch.setattr(updater, "_read_heartbeat", lambda: {"status": "starting", "epoch": 123.0, "timestamp_utc": "t1"})
    monkeypatch.setattr(updater, "telegram", lambda method, payload: {"ok": True})

    assert updater.send_status() is True
    assert updater.send_status() is False

    learning["observations"] = 11
    assert updater.send_status() is True


def test_provider_status_defaults_to_upstox_off(monkeypatch):
    import src.live_telegram_updater as updater

    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    monkeypatch.delenv("UPSTOX_ENABLED", raising=False)
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)

    mode, enabled, configured = updater._provider_telemetry()
    assert mode == "angel"
    assert enabled is False
    assert configured is False


def test_upstox_provider_defaults_disabled(monkeypatch):
    import src.alternative_market_data as alternative

    monkeypatch.delenv("UPSTOX_ENABLED", raising=False)
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    client = alternative.UpstoxMarketData()
    assert client.enabled is False
    assert client.available() is False
