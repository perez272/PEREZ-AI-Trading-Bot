from src import market_data_validation as validation


def test_disabled_secondary_validation_is_fail_open_without_fetch(monkeypatch):
    monkeypatch.setenv("UPSTOX_ENABLED", "false")
    ok, details = validation.validate_against_upstox("NIFTY", 25000.0)
    assert ok is True
    assert details["status"] == "DISABLED"


def test_invalid_secondary_age_fails_closed(monkeypatch):
    monkeypatch.setenv("UPSTOX_ENABLED", "true")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "token")
    monkeypatch.setattr(validation.upstox, "instrument_keys", lambda: {"NIFTY": "NSE_INDEX|99926000"})
    monkeypatch.setattr(
        validation.upstox,
        "get_snapshot",
        lambda symbol: {
            "closed_5m_close": 25000.0,
            "ltp": 25001.0,
            "candle_age_seconds": 500.0,
            "instrument_key": "NSE_INDEX|99926000",
        },
    )
    ok, details = validation.validate_against_upstox("NIFTY", 25000.0)
    assert ok is False
    assert details["status"] == "STALE_OR_INVALID_CANDLE"


def test_fresh_secondary_data_can_agree(monkeypatch):
    monkeypatch.setenv("UPSTOX_ENABLED", "true")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "token")
    monkeypatch.setattr(validation.upstox, "instrument_keys", lambda: {"NIFTY": "NSE_INDEX|99926000"})
    monkeypatch.setattr(
        validation.upstox,
        "get_snapshot",
        lambda symbol: {
            "closed_5m_close": 25000.02,
            "ltp": 25001.0,
            "candle_age_seconds": 30.0,
            "instrument_key": "NSE_INDEX|99926000",
        },
    )
    ok, details = validation.validate_against_upstox("NIFTY", 25000.0)
    assert ok is True
    assert details["status"] == "AGREE"
