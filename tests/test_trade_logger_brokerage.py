from src.trade_logger import log_closed_trade


def test_completed_trade_charges_brokerage_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("PAPER_TRADE_COST_INR", "30")
    trade = {"trade_id": "T1", "contract": "NIFTY", "symbol": "NIFTY"}
    result = {
        "time": "2026-11-22T04:00:00+00:00", "entry": 10, "current": 9,
        "exit_price": 9, "quantity": 0, "original_quantity": 1,
        "remaining_quantity": 0, "realized_pnl": -1, "unrealized_pnl": 0,
        "pnl": -1, "pnl_percent": -10, "exit_reason": "STOP_LOSS",
    }
    path = tmp_path / "trades.csv"
    first = log_closed_trade(trade, result, path)
    second = log_closed_trade(trade, result, path)
    assert first["brokerage_inr"] == 30.0
    assert first["net_pnl"] == -31.0
    assert float(second["net_pnl"]) == -31.0
    assert path.read_text().count("T1") == 1
