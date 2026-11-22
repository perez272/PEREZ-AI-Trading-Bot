from dashboard.server import _recorded_brokerage, performance


def test_dashboard_performance_deducts_recorded_brokerage():
    result = performance([{
        "trade_id": "T1", "contract": "NIFTY", "ts": "2026-11-22T10:00:00+05:30",
        "pnl": 20.0, "brokerage_inr": 30.0, "net_pnl": -10.0,
    }], start_capital=5000)
    assert result["gross_pnl"] == 20.0
    assert result["brokerage"] == 30.0
    assert result["total_pnl"] == -10.0
    assert result["equity"] == 4990.0
    assert result["win_rate_pct"] == 0.0


def test_dashboard_matches_recorded_trade_fee_by_trade_id(tmp_path):
    trades = tmp_path / "trades.csv"
    trades.write_text(
        "trade_id,closed_at,contract,pnl,brokerage_inr,net_pnl\n"
        "T2,2026-11-22T10:00:00+05:30,NIFTY,-5,30,-35\n",
        encoding="utf-8",
    )
    fees, unknown = _recorded_brokerage([{
        "trade_id": "T2", "contract": "NIFTY",
        "ts": "2026-11-22T10:00:00+05:30", "pnl": -5,
    }], trades_path=trades)
    assert fees == [30.0]
    assert unknown == 0
