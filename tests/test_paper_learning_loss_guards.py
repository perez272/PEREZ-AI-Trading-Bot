import src.risk_manager as risk


def _enable_paper_learning(monkeypatch, summary):
    import src.dashboard_control as dashboard

    monkeypatch.setattr(dashboard, "entries_allowed", lambda: True)
    monkeypatch.setattr(risk, "is_entry_window", lambda: True)
    monkeypatch.setattr(risk, "daily_summary", lambda: dict(summary))
    monkeypatch.setattr(risk, "_paper_learning_mode", lambda: True)
    monkeypatch.setattr(risk.TRADING_RISK_MANAGER, "is_circuit_breaker_active", lambda: False)


def test_paper_learning_mode_cannot_bypass_daily_loss_limit(monkeypatch):
    _enable_paper_learning(
        monkeypatch,
        {"closed_trades": 1, "pnl": -100.0, "consecutive_losses": 1,
         "losing_trades": 1, "worst_loss": -100.0},
    )

    allowed, reason, _ = risk.can_open_new_trade(capital=5000)

    assert not allowed
    assert reason == "Daily loss limit reached (2% of capital = Rs 100.00)"


def test_two_losing_trades_stop_applies_even_if_a_win_is_between_them(monkeypatch):
    _enable_paper_learning(
        monkeypatch,
        {"closed_trades": 3, "pnl": -50.0, "consecutive_losses": 1,
         "losing_trades": 2, "worst_loss": -120.0},
    )

    allowed, reason, _ = risk.can_open_new_trade(capital=5000)

    assert not allowed
    assert reason == "TWO_LOSING_TRADES_STOP"


def test_daily_summary_counts_all_losing_trades_not_only_consecutive(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    path = tmp_path / "trades.csv"
    path.write_text(
        "closed_at,pnl\\n"
        f"{today}T09:30:00+05:30,-120\\n"
        f"{today}T10:00:00+05:30,200\\n"
        f"{today}T10:30:00+05:30,-30\\n",
        encoding="utf-8",
    )

    summary = risk.daily_summary(path=path)

    assert summary["losing_trades"] == 2
    assert summary["consecutive_losses"] == 1
    assert summary["pnl"] == 50.0
