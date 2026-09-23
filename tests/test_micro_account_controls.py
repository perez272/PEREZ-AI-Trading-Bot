import logging

from src.micro_account_controls import (
    MICRO_ACCOUNT_CAPITAL,
    MAX_RISK_PER_TRADE_INR,
    MAX_ENTRY_CAPITAL_INR,
    MAX_DAILY_TRADES,
    build_strike_sequence,
    select_affordable_strike,
    calculate_rupee_stop_loss,
    spread_is_safe,
    daily_trade_limit_allows,
)


def test_build_strike_sequence_ce_starts_itm_then_moves_otm():
    assert build_strike_sequence("NIFTY", 25000, "CE", itm_depth=1) == [
        24950, 25000, 25050, 25100, 25150, 25200
    ]


def test_build_strike_sequence_pe_starts_itm_then_moves_otm():
    assert build_strike_sequence("NIFTY", 25000, "PE", itm_depth=1) == [
        25050, 25000, 24950, 24900, 24850, 24800
    ]


def test_select_affordable_strike_uses_live_ltp_and_4800_cap():
    contracts = {
        24950: {"symbol": "NIFTY24950CE", "token": "1", "lotsize": 25},
        25000: {"symbol": "NIFTY25000CE", "token": "2", "lotsize": 25},
        25050: {"symbol": "NIFTY25050CE", "token": "3", "lotsize": 25},
    }
    ltps = {24950: 210.0, 25000: 195.0, 25050: 190.0}
    result = select_affordable_strike(
        "NIFTY", 25000, "CE", contracts,
        lambda contract: ltps[contract["strike"]],
    )
    assert result["strike"] == 25050
    assert result["ltp"] == 190.0
    assert result["required_capital"] == 4750.0


def test_select_affordable_strike_returns_none_after_three_otm():
    contracts = {
        strike: {"symbol": str(strike), "token": str(strike), "lotsize": 25}
        for strike in [24950, 25000, 25050, 25100, 25150, 25200]
    }
    result = select_affordable_strike(
        "NIFTY", 25000, "CE", contracts, lambda _: 200.0
    )
    assert result is None


def test_rupee_stop_loss_is_exact():
    result = calculate_rupee_stop_loss(100.0, 25)
    assert result["max_points_loss"] == 30.0
    assert result["stop_loss"] == 70.0
    assert result["max_risk_inr"] == 750.0


def test_rupee_stop_loss_rejects_invalid_inputs():
    for entry, lot in [(0, 25), (100, 0), (-1, 25)]:
        try:
            calculate_rupee_stop_loss(entry, lot)
            assert False
        except ValueError:
            pass


def test_spread_guard_blocks_above_one_percent(caplog):
    with caplog.at_level(logging.WARNING):
        assert spread_is_safe(100.0, 102.0) is False
    assert "SPREAD_TOO_WIDE" in caplog.text


def test_spread_guard_allows_one_percent_or_less():
    assert spread_is_safe(100.0, 101.0) is True


def test_daily_trade_limit_blocks_at_two(caplog):
    with caplog.at_level(logging.WARNING):
        assert daily_trade_limit_allows(2) is False
    assert "MAX_DAILY_TRADES_HIT" in caplog.text


def test_daily_trade_limit_allows_below_two():
    assert daily_trade_limit_allows(1) is True


def test_create_trade_is_strictly_one_lot(monkeypatch):
    import src.trade_engine as engine

    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("ORDERS_ENABLED", "false")
    monkeypatch.setattr(engine, "claim_contract", lambda *args: (True, "claimed"))
    monkeypatch.setattr(engine, "record_event", lambda *args, **kwargs: "ts")

    resolved = {
        "status": "CONTRACT VALID",
        "option_type": "CE",
        "contract": "NIFTY 25000 CE",
        "exchange": "NFO",
        "token": "test-token",
        "expiry": "29 SEP 26",
        "strike": 25000,
        "lotsize": 25,
        "ltp": 50.0,
    }
    result = engine.create_trade("NIFTY", 25000, "BUY CE", 5000, resolved_contract=resolved)
    assert result["lots"] == 1
    assert result["quantity"] == 25
    assert result["investment"] == 1250.0


def test_daily_summary_counts_open_lifecycle_entries(monkeypatch, tmp_path):
    import json
    from datetime import datetime
    import src.risk_manager as risk

    trades = tmp_path / "trades.csv"
    trades.write_text("closed_at,pnl\n", encoding="utf-8")
    lifecycle = tmp_path / "data" / "paper_trade_lifecycle.jsonl"
    lifecycle.parent.mkdir(parents=True)
    lifecycle.write_text(
        json.dumps({"event": "OPEN", "ts_ist": "2026-09-23T10:00:00+05:30"}) + "\n"
        + json.dumps({"event": "OPEN", "ts_ist": "2026-09-23T11:00:00+05:30"}) + "\n"
        + json.dumps({"event": "CLOSE", "ts_ist": "2026-09-23T11:30:00+05:30"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    current = risk.IST.fromutc(datetime(2026, 9, 23, 6, 30))
    summary = risk.daily_summary(trades, current=current)
    assert summary["trades_taken_today"] == 2
