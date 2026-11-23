import json
import sqlite3

from src.ai_options_simulation import _paper_trades, _rejected_scenarios, _shadow_paths, _sniper_runner_comparisons, build_simulations


def test_paper_trade_path_uses_only_recorded_prices():
    events = [
        {"trade_id": "T1", "event": "OPEN", "ts_ist": "2026-11-06T10:00:00+05:30",
         "symbol": "NIFTY", "contract": "NIFTY CE", "entry": 100, "stop_loss": 90,
         "target1": 115, "target2": 125},
        {"trade_id": "T1", "event": "TARGET1_HIT", "ts_ist": "2026-11-06T10:05:00+05:30",
         "ltp": 116},
        {"trade_id": "T1", "event": "CLOSE", "ts_ist": "2026-11-06T10:10:00+05:30",
         "exit_price": 118, "pnl": 180, "exit_reason": "TARGET_2"},
    ]
    result = _paper_trades(events)
    assert len(result) == 1
    assert [point["price"] for point in result[0]["path"]] == [100, 116, 118]
    assert result[0]["entry"] == 100
    assert result[0]["pnl"] == 180
    assert result[0]["data_quality"] == "RECORDED_PATH"


def test_rejected_scenario_never_invents_missing_levels():
    result = _rejected_scenarios([{"id": 7, "symbol": "BANKNIFTY", "reason": "SPREAD_TOO_WIDE"}])
    assert result[0]["entry"] is None
    assert result[0]["stop_loss"] is None
    assert result[0]["data_quality"] == "INSUFFICIENT_RECORDED_DATA"
    assert "entry" in result[0]["missing_fields"]


def test_api_is_observation_only():
    result = build_simulations()
    assert result["safety"] == "OBSERVATION_ONLY"
    assert "no synthetic prices" in result["disclaimer"].lower()
    assert "sniper_expiry_observations" in result
    assert "sniper_runner_comparisons" in result



def test_rejected_surge_uses_only_recorded_shadow_horizon_prices(tmp_path):
    db_path = tmp_path / "adaptive.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE surge_candidates (
            id INTEGER PRIMARY KEY, event_key TEXT, symbol TEXT, option_type TEXT,
            instrument_key TEXT, expiry TEXT, strike REAL, detection_ts TEXT,
            entry_ltp REAL, score REAL, features_json TEXT, status TEXT, source TEXT
        )""")
        db.execute("""CREATE TABLE surge_outcomes (
            candidate_id INTEGER, h1_ltp REAL, h3_ltp REAL, h5_ltp REAL,
            h10_ltp REAL, h15_ltp REAL, mfe_pct REAL, mae_pct REAL,
            label TEXT, resolved_ts TEXT
        )""")
        db.execute("INSERT INTO surge_candidates VALUES (1,'evt-1','NIFTY','CE','NSE_FO|1','2026-11-06',25000,'2026-11-06T10:00:00+00:00',100,80,'{}','RESOLVED','live')")
        db.execute("INSERT INTO surge_outcomes VALUES (1,102,105,98,110,108,10,-2,'WIN','2026-11-06T10:15:00+00:00')")
    rejected = [{
        "id": 9, "symbol": "NIFTY", "reason": "SURGE:SPREAD_TOO_WIDE",
        "features_json": json.dumps({"event": {"event_key": "evt-1"}}),
    }]
    result = _shadow_paths(rejected, db_path)
    assert len(result) == 1
    assert [p["price"] for p in result[0]["path"]] == [100, 102, 105, 98, 110, 108]
    assert result[0]["return_pct"] == 8.0
    assert result[0]["pnl"] is None
    assert result[0]["stop_loss"] is None
    assert result[0]["data_quality"] == "RECORDED_SHADOW_PATH"


def test_shadow_path_ignores_unmatched_rejection(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE surge_candidates (id INTEGER, event_key TEXT)")
        db.execute("CREATE TABLE surge_outcomes (candidate_id INTEGER)")
    assert _shadow_paths([{"id": 1, "features_json": "{}"}], db_path) == []


def test_paper_trade_accounting_joins_csv_by_trade_id_and_keeps_gross(tmp_path):
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text(
        "trade_id,pnl,brokerage_inr,net_pnl\nT-1,125,30,95\n",
        encoding="utf-8",
    )
    events = [
        {"trade_id": "T-1", "event": "OPEN", "entry": 100, "quantity": 25},
        {"trade_id": "T-1", "event": "CLOSE", "pnl": 125, "exit_price": 105},
    ]
    trade = _paper_trades(events, csv_path)[0]
    assert trade["pnl"] == trade["recorded_gross_pnl"] == 125
    assert trade["recorded_brokerage_inr"] == 30
    assert trade["recorded_net_pnl"] == 95
    assert trade["accounting_source"] == "data/trades.csv"


def test_missing_accounting_fee_is_not_assumed_zero(tmp_path):
    csv_path = tmp_path / "trades.csv"
    csv_path.write_text("trade_id,pnl\nT-2,50\n", encoding="utf-8")
    trade = _paper_trades([
        {"trade_id": "T-2", "event": "OPEN", "entry": 100},
        {"trade_id": "T-2", "event": "CLOSE", "pnl": 50},
    ], csv_path)[0]
    assert trade["recorded_gross_pnl"] == 50
    assert trade["recorded_brokerage_inr"] is None
    assert trade["recorded_net_pnl"] is None


def test_api_runner_comparisons_expose_all_nine_scenarios_and_gross_net():
    paper = [{
        "id": "T-9", "symbol": "NIFTY", "contract": "NIFTY CE",
        "recorded_gross_pnl": 100, "recorded_brokerage_inr": 25,
        "recorded_net_pnl": 75, "accounting_source": "data/trades.csv",
        "entry": 100, "stop_loss": 90, "quantity": 25,
        "path": [{"price": p} for p in (100, 120, 145, 170, 160)],
    }]
    result = _sniper_runner_comparisons(paper)[0]
    assert result["recorded_gross_pnl"] == 100
    assert result["recorded_brokerage_inr"] == 25
    assert result["recorded_net_pnl"] == 75
    assert result["scenario_count"] == 9
    assert len(result["scenarios"]) == 9
    assert {x["activation_pct"] for x in result["scenarios"]} == {40.0, 45.0, 50.0}
    assert {x["atr_multiple"] for x in result["scenarios"]} == {1.0, 1.5, 2.0}
