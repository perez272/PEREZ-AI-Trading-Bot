from src.sniper_expiry_simulation import (
    build_sniper_observations, evaluate_sniper_signal, select_sniper_contract,
    simulate_runner,
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
