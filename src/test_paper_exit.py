from pathlib import Path

from src.live_trade_monitor import run_monitor


def target_price(*_):
    return 107.0


def stop_loss_price(*_):
    return 98.0


base_trade = {
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
    "target": 107.0,
}

log_file = "data/trades_test.csv"

target_result = run_monitor(
    base_trade,
    poll_seconds=0,
    get_ltp=target_price,
    notify=False,
    log_path=log_file,
)
assert target_result["exit_reason"] == "TARGET"

stop_result = run_monitor(
    base_trade,
    poll_seconds=0,
    get_ltp=stop_loss_price,
    notify=False,
    log_path=log_file,
)
assert stop_result["exit_reason"] == "STOP_LOSS"

assert Path(log_file).exists()
print("PASS: target close, stop-loss close, and CSV logging.")
