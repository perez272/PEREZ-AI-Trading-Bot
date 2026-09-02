from pathlib import Path

from src.live_trade_monitor import run_monitor


def target_price(*_):
    return 107.0


def stop_loss_price(*_):
    return 98.0


def _base_trade():
    return {
        "symbol": "TEST",
        "signal": "BUY CE",
        "contract": "TESTCONTRACT",
        "exchange": "TEST",
        "token": "TEST",
        "entry": 100.0,
        "quantity": 10,
        "lots": 1,
        "investment": 1000.0,
        "stop_loss": 98.0,
        "target1": 104.0,
        "target2": 107.0,
    }


def test_target_and_stop_loss(tmp_path):
    log_file = tmp_path / "trades_test.csv"

    target_result = run_monitor(
        _base_trade(),
        poll_seconds=0,
        get_ltp=target_price,
        notify=False,
        log_path=str(log_file),
    )
    assert target_result["closed"] is True
    assert target_result["exit_reason"] == "MARKET_CLOSE"

    stop_result = run_monitor(
        _base_trade(),
        poll_seconds=0,
        get_ltp=stop_loss_price,
        notify=False,
        log_path=str(log_file),
    )
    assert stop_result["closed"] is True
    assert stop_result["exit_reason"] == "TRAILING_STOP"
    assert Path(log_file).exists()
