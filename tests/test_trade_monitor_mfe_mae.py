from src.trade_monitor import monitor_trade


def _trade():
    return {
        "contract": "TESTCE",
        "entry": 100.0,
        "quantity": 10,
        "original_quantity": 10,
        "remaining_quantity": 10,
        "initial_stop_loss": 95.0,
        "stop_loss": 95.0,
        "target1": 110.0,
        "target2": 120.0,
        "partial_booked": False,
        "realized_pnl": 0.0,
    }


def test_mfe_mae_accumulate_across_observations():
    trade = _trade()
    first = monitor_trade(trade, 97.0)
    assert first["mfe"] == 0.0
    assert first["mae"] == -3.0

    second = monitor_trade(trade, 106.0)
    assert second["mfe"] == 6.0
    assert second["mae"] == -3.0

    third = monitor_trade(trade, 102.0)
    assert third["mfe"] == 6.0
    assert third["mae"] == -3.0
    assert trade["high_watermark"] == 106.0
    assert trade["low_watermark"] == 97.0
