from src import trade_monitor


def _trade(expiry="2026-10-24"):
    return {
        "trade_id": "TEST-EXPIRY-TRAIL",
        "symbol": "NIFTY",
        "contract": "NIFTY TEST CE",
        "expiry": expiry,
        "entry": 100.0,
        "quantity": 25,
        "original_quantity": 25,
        "remaining_quantity": 25,
        "initial_stop_loss": 98.0,
        "stop_loss": 98.0,
        "target1": 105.0,
        "target2": 110.0,
        "partial_booked": False,
        "realized_pnl": 0.0,
    }


def _fix_clock(monkeypatch, stamp="2026-10-24T05:00:00+00:00"):
    monkeypatch.setattr(trade_monitor, "now_utc", lambda: stamp)
    monkeypatch.setattr(trade_monitor, "release_contract", lambda *args, **kwargs: None)


def test_expiry_day_bypasses_fixed_targets_and_activates_trail(monkeypatch):
    _fix_clock(monkeypatch)
    trade = _trade()

    result = trade_monitor.monitor_trade(trade, 120.0)

    assert result["closed"] is False
    assert result["expiry_day"] is True
    assert result["expiry_trailing_active"] is True
    assert result["stop_loss"] == 105.0
    assert result["target1_hit"] is False
    assert result["remaining_quantity"] == 25


def test_expiry_day_hard_stop_remains_until_activation(monkeypatch):
    _fix_clock(monkeypatch)
    trade = _trade()

    result = trade_monitor.monitor_trade(trade, 114.0)

    assert result["closed"] is False
    assert result["expiry_trailing_active"] is False
    assert result["stop_loss"] == 98.0
    assert result["target1_hit"] is False


def test_expiry_trail_ratchets_and_exits_on_reversal(monkeypatch):
    _fix_clock(monkeypatch)
    trade = _trade()
    trade["high_watermark"] = 120.0
    trade["expiry_trailing_active"] = True
    trade["stop_loss"] = 105.0

    result = trade_monitor.monitor_trade(trade, 104.0)

    assert result["closed"] is True
    assert result["exit_reason"] == "TRAILING_STOP"
    assert result["exit_price"] == 105.0
    assert result["pnl"] == 125.0


def test_non_expiry_trade_keeps_existing_target_behavior(monkeypatch):
    _fix_clock(monkeypatch)
    trade = _trade(expiry="2026-10-27")

    result = trade_monitor.monitor_trade(trade, 110.0)

    assert result["closed"] is True
    assert result["expiry_day"] is False
    assert result["exit_reason"] == "TARGET_2"
    assert result["target1_hit"] is True
