from datetime import datetime

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


def test_hybrid_normal_day_target_exits_full_one_lot():
    trade = _trade()
    trade.update({
        "index_name": "NIFTY",
        "hard_sl_price": 98.0,
        "target_1_price": 104.0,
    })

    result = monitor_trade(trade, 104.0, current_date=datetime(2026, 9, 23))

    assert result["closed"] is True
    assert result["exit_reason"] == "TARGET_1"
    assert result["remaining_quantity"] == 0
    assert result["quantity"] == 0
    assert result["realized_pnl"] == 40.0


def test_hybrid_expiry_day_uses_trailing_exit_and_ignores_target():
    trade = _trade()
    trade.update({
        "index_name": "NIFTY",
        "hard_sl_price": 98.0,
        "target_1_price": 104.0,
    })

    result = monitor_trade(trade, 120.0, current_date=datetime(2026, 9, 29))
    assert result["closed"] is False
    assert result["trailing_sl_price"] == 105.0

    result = monitor_trade(trade, 104.0, current_date=datetime(2026, 9, 29))
    assert result["closed"] is True
    assert result["exit_reason"] == "TRAILING_STOP"
    assert result["exit_price"] == 105.0
    assert result["remaining_quantity"] == 0
    assert result["quantity"] == 0
