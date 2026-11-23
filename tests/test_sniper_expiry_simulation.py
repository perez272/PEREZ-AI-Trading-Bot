from src.sniper_expiry_simulation import (
    build_sniper_observations, evaluate_sniper_signal, select_sniper_contract,
    simulate_runner, compare_runner_scenarios,
)


def _observation():
    return {
        "symbol": "NIFTY", "expiry_bucket": "0DTE",
        "observed_at": "2026-11-24T10:00:00+05:30",
        "spot": 25120, "strike_step": 50, "max_pain_strike": 25000,
        "pinning_candidate": False,
        "oi_evidence": [{"side": "CE", "strike": 25100,
                         "oi_change": -12000, "premium_change": 8.5}],
    }


def _context():
    return {
        "breakout_direction": "CE", "breakout_level": 25100,
        "orb_breakout": True,
        "mtf_moves_pct": {"1m": 0.08, "3m": 0.14, "5m": 0.20},
        "option_volume_ratio": 2.4,
    }


def test_sniper_requires_all_confluence_conditions():
    result = evaluate_sniper_signal(_observation(), _context())
    assert result["eligible"] is True
    assert result["status"] == "SNIPER_CONFLUENCE_CONFIRMED"
    assert all(result["checks"].values())
    assert result["safety"] == "OBSERVATION_ONLY"


def test_missing_market_context_fails_closed():
    result = evaluate_sniper_signal(_observation())
    assert result["eligible"] is False
    assert "ORB_OR_SESSION_BREAKOUT_UNCONFIRMED" in result["rejection_reasons"]
    assert "OPTION_VOLUME_SPIKE_MISSING" in result["rejection_reasons"]


def test_midday_and_max_pain_pinning_are_rejected():
    observation = _observation()
    observation["observed_at"] = "2026-11-24T12:00:00+05:30"
    observation["spot"] = 25010
    observation["max_pain_strike"] = 25000
    result = evaluate_sniper_signal(observation, _context())
    assert "MIDDAY_CHOP_WINDOW" in result["rejection_reasons"]
    assert "MAX_PAIN_PINNING" in result["rejection_reasons"]


def test_late_zero_dte_and_wrong_expiry_are_rejected():
    observation = _observation()
    observation["observed_at"] = "2026-11-24T14:15:00+05:30"
    result = evaluate_sniper_signal(observation, _context())
    assert "0DTE_ENTRY_CUTOFF" in result["rejection_reasons"]
    observation["expiry_bucket"] = "OTHER"
    assert "NOT_0DTE_OR_1DTE" in evaluate_sniper_signal(observation, _context())["rejection_reasons"]


def test_oi_unwind_requires_matching_option_side_and_premium_rise():
    observation = _observation()
    observation["oi_evidence"][0]["side"] = "PE"
    result = evaluate_sniper_signal(observation, _context())
    assert result["eligible"] is False
    assert "ATM_NEAR_ITM_WRITER_UNWIND_MISSING" in result["rejection_reasons"]


def test_contract_selection_requires_gamma_delta_and_4200_whole_lot_cap():
    candidates = [
        {"side": "CE", "strike": 25100, "ltp": 100, "delta": 0.52,
         "gamma": 0.03, "lot_size": 25, "volume_ratio": 2.0},
        {"side": "CE", "strike": 25150, "ltp": 100, "delta": 0.50,
         "gamma": 0.05, "lot_size": 50, "volume_ratio": 3.0},
        {"side": "CE", "strike": 25200, "ltp": 10, "delta": 0.10,
         "gamma": 0.20, "lot_size": 25, "volume_ratio": 5.0},
        {"side": "CE", "strike": 25100, "ltp": 100, "delta": 0.52,
         "lot_size": 25},
    ]
    result = select_sniper_contract(candidates, 25120, 50, "CE")
    assert result["selected"]["strike"] == 25100
    assert result["selected"]["estimated_entry_cost"] == 2500
    assert all(item["estimated_entry_cost"] <= 4200 for item in result["candidates"])


def test_runner_keeps_full_quantity_and_deducts_flat_brokerage():
    path = [{"price": price} for price in (100, 115, 130, 150, 180, 170, 160)]
    result = simulate_runner(path, entry=100, initial_stop=90, quantity=25)
    assert result["runner_activated"] is True
    assert result["quantity"] == 25
    assert result["brokerage_inr"] == 30
    assert result["net_pnl"] == result["gross_pnl"] - 30
    assert result["final_stop"] >= 101.2


def test_no_runner_result_without_recorded_prices():
    result = simulate_runner([], entry=100, initial_stop=90, quantity=25)
    assert result["status"] == "NO_RECORDED_PATH"
    assert result["net_pnl"] is None


def test_existing_observations_without_context_are_rejected():
    result = build_sniper_observations([_observation()])
    assert len(result) == 1
    assert result[0]["eligible"] is False



def test_contract_selector_uses_maximum_affordable_whole_lots():
    candidates = [{
        "side": "CE", "strike": 25100, "ltp": 40, "delta": 0.52,
        "gamma": 0.04, "lot_size": 25, "volume_ratio": 2.0,
    }]
    result = select_sniper_contract(candidates, 25120, 50, "CE")
    selected = result["selected"]
    assert selected["affordable_lots"] == 4
    assert selected["whole_lot_quantity"] == 100
    assert selected["estimated_entry_cost"] == 4000
    assert selected["whole_lot_quantity"] % selected["lot_size"] == 0


def test_runner_scenario_comparison_replays_same_recorded_path():
    path = [{"price": price} for price in (100, 115, 145, 170, 160, 155)]
    result = compare_runner_scenarios(path, entry=100, initial_stop=90, quantity=25)
    assert result["status"] == "READY"
    assert result["scenario_count"] == 9
    assert len(result["scenarios"]) == 9
    assert result["comparison_basis"] == "SAME_RECORDED_OPTION_PREMIUM_PATH"
    assert result["safety"] == "SIMULATION_ONLY"
    assert result["best_observed_scenario"]["net_pnl"] == max(
        item["net_pnl"] for item in result["scenarios"]
    )


def test_runner_scenario_comparison_without_path_does_not_invent_results():
    result = compare_runner_scenarios([], entry=100, initial_stop=90, quantity=25)
    assert result["status"] == "INSUFFICIENT_RECORDED_PATH"
    assert result["best_observed_scenario"] is None
    assert all(item["net_pnl"] is None for item in result["scenarios"])


def test_runner_reports_activation_threshold_and_max_favorable_move():
    path = [{"price": p} for p in (100, 110, 120, 130)]
    result = simulate_runner(path, entry=100, initial_stop=90, quantity=25,
                             activation_pct=45.0)
    assert result["activation_status"] == "NOT_REACHED"
    assert result["activation_reason"] == "MAX_FAVORABLE_MOVE_BELOW_THRESHOLD"
    assert result["activation_threshold_price"] == 145
    assert result["max_favorable_price"] == 130
    assert result["max_favorable_pct"] == 30


def test_runner_diagnostics_show_activation_when_threshold_crossed():
    result = simulate_runner([{"price": 100}, {"price": 146}, {"price": 140}],
                             entry=100, initial_stop=90, quantity=25)
    assert result["runner_activated"] is True
    assert result["activation_status"] == "ACTIVATED"
    assert result["activation_reason"] == "THRESHOLD_REACHED"
    assert result["max_favorable_pct"] == 46



def test_runner_gap_through_stop_fills_at_observed_price_not_stop():
    result = simulate_runner(
        [{"price": 100}, {"price": 146}, {"price": 80}],
        entry=100, initial_stop=90, quantity=25, brokerage=30,
    )
    assert result["status"] == "TRAIL_EXIT"
    assert result["stop_trigger_price"] is not None
    assert result["exit_price"] == 80
    assert result["gross_pnl"] == -500
    assert result["net_pnl"] == -530
    assert result["execution_basis"] == "RECORDED_OBSERVATION_CONSERVATIVE_GAP_FILL"


def test_runner_does_not_apply_new_trailing_stop_to_same_observation():
    # The activation quote establishes the new stop; only the next quote can hit it.
    result = simulate_runner(
        [{"price": 100}, {"price": 146}, {"price": 100}],
        entry=100, initial_stop=90, quantity=25, brokerage=30,
    )
    assert result["status"] == "TRAIL_EXIT"
    assert result["observations_used"] == 3
    assert result["exit_price"] == 100
    assert result["position_model"] == "FULL_QUANTITY_COUNTERFACTUAL_NO_PARTIAL_EXITS"


def test_runner_rejects_invalid_quantity_and_fee_inputs():
    bad_quantity = simulate_runner([{"price": 100}], 100, 90, 0)
    bad_fee = simulate_runner([{"price": 100}], 100, 90, 25, brokerage=-1)
    assert bad_quantity["status"] == "INSUFFICIENT_INPUT"
    assert bad_fee["status"] == "INSUFFICIENT_INPUT"
