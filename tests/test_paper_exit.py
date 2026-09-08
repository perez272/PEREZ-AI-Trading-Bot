from pathlib import Path

from src.live_trade_monitor import run_monitor


def target2_price(*_):
    return 107.0


def stop_loss_price(*_):
    return 98.0


def _base_trade():
    return {
        "trade_id": "TEST-T2-LIFECYCLE-001",
        "symbol": "TEST",
        "signal": "BUY CE",
        "contract": "TESTCONTRACT",
        "exchange": "TEST",
        "token": "TEST",
        "entry": 100.0,
        "quantity": 10,
        "original_quantity": 10,
        "remaining_quantity": 10,
        "lots": 1,
        "investment": 1000.0,
        "stop_loss": 98.0,
        "initial_stop_loss": 98.0,
        "target1": 104.0,
        "target2": 107.0,
        "target": 107.0,
        "partial_booked": False,
        "realized_pnl": 0.0,
    }


def test_target2_closes_remaining_position(tmp_path):
    log_file = tmp_path / "trades_test.csv"

    result = run_monitor(
        _base_trade(),
        poll_seconds=0,
        get_ltp=target2_price,
        notify=False,
        log_path=str(log_file),
        persist_outcome=False,
    )

    assert result["closed"] is True
    assert result["exit_reason"] == "TARGET_2"
    assert result["status"] == "TARGET 2 HIT"

    # T1 books 5 units at 104 = +20.
    # T2 closes remaining 5 units at 107 = +35.
    # Total = +55.
    assert result["original_quantity"] == 10
    assert result["remaining_quantity"] == 0
    assert result["quantity"] == 0
    assert result["realized_pnl"] == 55.0
    assert result["pnl"] == 55.0
    assert result["pnl_percent"] == 5.5

    assert Path(log_file).exists()


def test_stop_loss_closes_position(tmp_path):
    log_file = tmp_path / "trades_test.csv"

    result = run_monitor(
        _base_trade(),
        poll_seconds=0,
        get_ltp=stop_loss_price,
        notify=False,
        log_path=str(log_file),
        persist_outcome=False,
    )

    assert result["closed"] is True
    assert result["exit_reason"] == "STOP_LOSS"
    assert result["status"] == "STOP LOSS HIT"
    assert result["remaining_quantity"] == 10
    assert result["pnl"] == -20.0
    assert result["pnl_percent"] == -2.0
    assert Path(log_file).exists()
