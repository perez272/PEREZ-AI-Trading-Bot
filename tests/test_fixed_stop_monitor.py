from src.trade_monitor import monitor_trade


def _trade():
    return {
        "trade_id": "TEST-FIXED-SL-001",
        "symbol": "TEST",
        "contract": "TEST_FIXED_SL",
        "entry": 100.0,
        "quantity": 10,
        "original_quantity": 10,
        "remaining_quantity": 10,
        "initial_stop_loss": 98.0,
        "stop_loss": 98.0,
        "target1": 104.0,
        "target2": 110.0,
        "partial_booked": False,
        "realized_pnl": 0.0,
    }


def test_stop_remains_fixed_after_target1():
    trade = _trade()
    result = monitor_trade(trade, 104.0)

    assert result["closed"] is False
    assert result["target1_hit"] is True
    assert result["stop_loss"] == 98.0
    assert trade["stop_loss"] == 98.0


def test_fixed_stop_closes_at_original_stop():
    trade = _trade()
    monitor_trade(trade, 104.0)
    result = monitor_trade(trade, 98.0)

    assert result["closed"] is True
    assert result["exit_reason"] == "STOP_LOSS"
    assert result["exit_price"] == 98.0
    assert result["stop_loss"] == 98.0
