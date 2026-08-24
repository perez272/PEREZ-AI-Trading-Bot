from src import ai_memory
from src import live_trade_monitor


def _trade():
    return {
        "trade_id": "PEREZ-INTEGRATION-001",
        "symbol": "NIFTY",
        "signal": "BUY CE",
        "contract": "NIFTY-TEST-CE",
        "exchange": "NFO",
        "token": "TEST",
        "expiry": "2026-08-27",
        "strike": 25000,
        "entry": 10.0,
        "quantity": 1,
        "remaining_quantity": 1,
        "initial_stop_loss": 9.8,
        "stop_loss": 9.8,
        "target1": 10.5,
        "target2": 11.0,
        "realized_pnl": 0.0,
        "investment": 10.0,
        "ensemble_score": 82,
        "options_score": 78,
        "ai_confidence": 55,
    }


def test_closed_paper_trade_monitor_to_memory_end_to_end(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    ai_memory.DB_PATH = db

    monkeypatch.setattr(live_trade_monitor, "get_ltp", lambda exchange, contract, token: 11.0)
    monkeypatch.setattr(live_trade_monitor, "should_force_exit", lambda: False)
    monkeypatch.setattr(live_trade_monitor, "send_exit_alert", lambda trade, result: None)
    monkeypatch.setattr(live_trade_monitor, "send_alert", lambda message: None)
    monkeypatch.setattr(live_trade_monitor, "log_closed_trade", lambda trade, result, log_path: {"trade_id": trade["trade_id"]})

    trade = _trade()
    result = live_trade_monitor.run_monitor(trade, poll_seconds=0, notify=False, log_path=str(tmp_path / "trades.csv"))

    assert result["closed"] is True
    assert result["exit_reason"] == "TARGET2"

    # The monitor itself must persist the outcome at the closure boundary.
    summary = ai_memory.learning_summary()
    assert summary["overall"]["n"] == 1
    assert summary["overall"]["wins"] == 1
    assert summary["overall"]["pnl"] == 1.0
    assert summary["recent"][0]["trade_id"] == trade["trade_id"]

    # A higher-level reconciliation is safe and must not double-learn it.
    first = ai_memory.remember_outcome(trade, result, regime="TRENDING")
    assert first["stored"] is False
    assert first["duplicate"] is True


def test_outcome_without_trade_id_is_rejected(tmp_path):
    ai_memory.DB_PATH = tmp_path / "memory.db"
    trade = _trade()
    trade.pop("trade_id")
    result = {"closed": True, "pnl": 1.0, "pnl_percent": 10.0, "exit_reason": "TARGET2"}

    try:
        ai_memory.remember_outcome(trade, result)
    except ValueError as exc:
        assert str(exc) == "CLOSED_PAPER_TRADE_MISSING_TRADE_ID"
    else:
        raise AssertionError("Outcome without canonical trade_id must never enter learning memory")
