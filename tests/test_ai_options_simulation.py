from src.ai_options_simulation import _paper_trades, _rejected_scenarios, build_simulations


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
    assert "No synthetic prices" in result["disclaimer"]
