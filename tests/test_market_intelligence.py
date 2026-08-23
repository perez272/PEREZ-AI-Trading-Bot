import math

import src.market_intelligence as mi


def test_black_scholes_call_is_positive():
    result = mi._black_scholes(25000, 25000, 7 / 365, 0.065, 0.20, "CE")
    assert result["price"] > 0
    assert 0 < result["delta"] < 1
    assert result["gamma"] > 0
    assert result["vega"] > 0


def test_black_scholes_put_delta_is_negative():
    result = mi._black_scholes(25000, 25000, 7 / 365, 0.065, 0.20, "PE")
    assert result["price"] > 0
    assert -1 < result["delta"] < 0


def test_implied_volatility_recovers_known_volatility():
    spot = 25000
    strike = 25000
    years = 7 / 365
    expected = 0.20
    market_price = mi._black_scholes(spot, strike, years, 0.065, expected, "CE")["price"]
    recovered = mi._implied_volatility(market_price, spot, strike, years, "CE")
    assert recovered is not None
    assert math.isclose(recovered, expected, rel_tol=0.02, abs_tol=0.005)


def test_intelligence_rejects_wide_spread_without_broker_calls(monkeypatch):
    monkeypatch.setattr(mi, "_fetch_greeks", lambda *args, **kwargs: {
        "available": True,
        "source": "test",
        "delta": 0.55,
        "gamma": 0.001,
        "theta": -10,
        "vega": 20,
        "iv_pct": 25,
    })
    monkeypatch.setattr(mi, "_fetch_pcr", lambda: {})
    monkeypatch.setattr(mi, "_load_state", lambda: {})
    monkeypatch.setattr(mi, "_save_state", lambda state: None)

    candidate = {
        "symbol": "NIFTY",
        "option_type": "CE",
        "expiry": "28AUG2026",
        "ltp": 80,
        "open_interest": 100000,
        "percent_change": 2.0,
        "spread_pct": 2.0,
        "slippage_pct": 0.1,
        "best_bid": 79,
        "best_ask": 81,
    }
    contract = {"expiry": "28AUG2026", "strike": 25000}

    monkeypatch.setattr(mi, "get_client", lambda: None)
    result = mi.enrich_option_intelligence(candidate, contract)
    assert result["intelligence_hard_fail"] is True
    assert "WIDE_SPREAD" in result["intelligence_reasons"]


def test_oi_change_is_only_awarded_after_previous_observation(monkeypatch, tmp_path):
    state_file = tmp_path / "oi.json"
    monkeypatch.setattr(mi, "STATE_PATH", state_file)
    monkeypatch.setattr(mi, "_fetch_greeks", lambda *args, **kwargs: {
        "available": True,
        "source": "test",
        "delta": 0.55,
        "gamma": 0.001,
        "theta": -10,
        "vega": 20,
        "iv_pct": 25,
    })
    monkeypatch.setattr(mi, "_fetch_pcr", lambda: {})
    monkeypatch.setattr(mi, "get_client", lambda: None)

    base = {
        "symbol": "NIFTY",
        "option_type": "CE",
        "expiry": "28AUG2026",
        "ltp": 80,
        "open_interest": 100000,
        "percent_change": 2.0,
        "spread_pct": 0.2,
        "slippage_pct": 0.1,
        "best_bid": 79.9,
        "best_ask": 80.1,
    }
    contract = {"expiry": "28AUG2026", "strike": 25000}

    first = mi.enrich_option_intelligence(base, contract)
    assert first["oi_change_available"] is False

    second = mi.enrich_option_intelligence({**base, "open_interest": 105000, "ltp": 82}, contract)
    assert second["oi_change_available"] is True
    assert second["oi_change_pct"] > 0
