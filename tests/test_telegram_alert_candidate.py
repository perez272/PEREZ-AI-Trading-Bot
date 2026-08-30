from src.telegram_alert import _entry_reason


def test_entry_reason_exposes_validation_context():
    trade = {
        "signal": "BUY CE",
        "underlying_score": 84,
        "options_score": 78,
        "mtf_direction": "BULLISH",
        "strategy": "INDEX_MOMENTUM_SCALP",
    }
    reason = _entry_reason(trade)
    assert "Underlying signal BUY CE" in reason
    assert "underlying score 84/100" in reason
    assert "option gate score 78/100" in reason
    assert "MTF BULLISH" in reason
    assert "strategy INDEX_MOMENTUM_SCALP" in reason


def test_entry_reason_falls_back_when_optional_context_missing():
    assert _entry_reason({}) == "All paper-trade validation gates passed"
