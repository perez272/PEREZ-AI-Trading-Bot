import csv
from pathlib import Path

from src.trade_logger import log_closed_trade


def test_log_closed_trade_is_idempotent(tmp_path):
    path = tmp_path / "trades.csv"

    trade = {
        "trade_id": "regression-duplicate-test",
        "underlying": "BANKNIFTY",
        "signal": "BUY CE",
        "contract": "BANKNIFTY TEST CE",
        "exchange": "NFO",
        "entry": 100.0,
        "original_quantity": 30,
        "quantity": 30,
        "remaining_quantity": 0,
        "exit_quantity": 30,
        "remaining_quantity": 30,
        "lots": 1,
        "investment": 3000.0,
    }

    result = {
        "time": "2026-09-11 12:00:00",
        "entry": 100.0,
        "current": 105.0,
        "realized_pnl": 150.0,
        "unrealized_pnl": 0.0,
        "pnl": 150.0,
        "pnl_percent": 5.0,
        "exit_reason": "TEST",
    }

    first = log_closed_trade(trade, result, str(path))
    second = log_closed_trade(trade, result, str(path))

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))

    assert first["trade_id"] == "regression-duplicate-test"
    assert second["trade_id"] == "regression-duplicate-test"
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "regression-duplicate-test"
