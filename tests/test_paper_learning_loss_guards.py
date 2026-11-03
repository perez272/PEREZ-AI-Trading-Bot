import src.risk_manager as risk


def _enable_paper_learning(monkeypatch, summary):
    import src.dashboard_control as dashboard

    monkeypatch.setattr(dashboard, "entries_allowed", lambda: True)
    monkeypatch.setattr(risk, "is_entry_window", lambda: True)
    monkeypatch.setattr(risk, "daily_summary", lambda: dict(summary))
    monkeypatch.setattr(risk, "_paper_learning_mode", lambda: True)
    monkeypatch.setattr(risk.TRADING_RISK_MANAGER, "is_circuit_breaker_active", lambda: False)


def test_paper_learning_mode_cannot_bypass_daily_loss_limit(monkeypatch):
    _enable_paper_learning(monkeypatch,
        {"closed_trades": 1, "pnl": -100.0, "consecutive_losses": 1, "losing_trades": 1, "worst_loss": -100.0})
    allowed, reason, _ = risk.can_open_new_trade(capital=5000)
    assert not allowed
    assert reason == "Daily loss limit reached (2% of capital = Rs 100.00)"


def test_two_losses_with_a_win_between_them_trigger_daily_lock(monkeypatch):
    _enable_paper_learning(monkeypatch,
        {"closed_trades": 3, "pnl": 50.0, "consecutive_losses": 1, "losing_trades": 2, "worst_loss": -120.0})
    allowed, reason, _ = risk.can_open_new_trade(capital=5000)
    assert not allowed
    assert reason == "TWO_LOSING_TRADES_STOP"


def test_one_loss_does_not_trigger_two_loss_daily_lock(monkeypatch):
    _enable_paper_learning(monkeypatch,
        {"closed_trades": 1, "pnl": -30.0, "consecutive_losses": 1, "losing_trades": 1, "worst_loss": -30.0})
    allowed, reason, _ = risk.can_open_new_trade(capital=5000)
    assert allowed
    assert "no arbitrary daily trade-count cap" in reason


def test_daily_summary_counts_losses_by_ist_market_date(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    current = datetime(2026, 11, 3, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    path = tmp_path / "trades.csv"
    path.write_text(
        "closed_at,pnl\n"
        "2026-11-03T00:05:00+00:00,-120\n"
        "2026-11-03T04:30:00+00:00,200\n"
        "2026-11-03T05:00:00+00:00,-30\n"
        "2026-11-02T17:00:00+00:00,-999\n",
        encoding="utf-8",
    )
    summary = risk.daily_summary(path=path, current=current)
    assert summary["closed_trades"] == 3
    assert summary["losing_trades"] == 2
    assert summary["consecutive_losses"] == 1
    assert summary["pnl"] == 50.0


def test_two_loss_daily_lock_precedes_three_loss_circuit_breaker(monkeypatch):
    _enable_paper_learning(monkeypatch,
        {"closed_trades": 3, "pnl": -50.0, "consecutive_losses": 3, "losing_trades": 3, "worst_loss": -30.0})
    allowed, reason, _ = risk.can_open_new_trade(capital=5000)
    assert not allowed
    assert reason == "TWO_LOSING_TRADES_STOP"

