from datetime import datetime
from zoneinfo import ZoneInfo

import math
import pandas as pd
import pytest

from src.black_scholes_engine import (
    black_scholes_greeks,
    calculate_chain_greeks,
    compare_broker_greeks,
    implied_volatility,
    time_to_expiry_years,
)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=IST)


@pytest.mark.parametrize("kind", ["CE", "PE"])
def test_implied_volatility_recovers_known_volatility(kind):
    years = 1.0 / 12.0
    expected_iv = 0.24
    theoretical = black_scholes_greeks(
        25000, 25000, years, 0.06, 0.01, expected_iv, kind
    )["price"]
    recovered = implied_volatility(
        theoretical, 25000, 25000, years, 0.06, 0.01, kind
    )
    assert recovered == pytest.approx(expected_iv, abs=2e-6)


def test_call_delta_and_put_delta_have_expected_signs():
    call = black_scholes_greeks(25000, 25000, 0.05, 0.06, 0.01, 0.2, "CE")
    put = black_scholes_greeks(25000, 25000, 0.05, 0.06, 0.01, 0.2, "PE")
    assert 0 < call["delta"] < 1
    assert -1 < put["delta"] < 0
    assert call["gamma"] > 0
    assert put["gamma"] > 0


def test_put_call_parity():
    s, k, t, r, q, vol = 25000, 25000, 0.08, 0.06, 0.01, 0.22
    call = black_scholes_greeks(s, k, t, r, q, vol, "CE")["price"]
    put = black_scholes_greeks(s, k, t, r, q, vol, "PE")["price"]
    lhs = call - put
    rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
    assert lhs == pytest.approx(rhs, abs=1e-8)


def test_date_only_expiry_is_1530_ist():
    expiry = time_to_expiry_years("2026-11-02", NOW)
    expected_seconds = 5.5 * 60 * 60
    assert expiry == pytest.approx(expected_seconds / (365 * 24 * 60 * 60))


def test_chain_uses_bid_ask_mid_and_returns_greeks():
    expiry = datetime(2026, 11, 30, 15, 30, tzinfo=IST)
    years = time_to_expiry_years(expiry, NOW)
    theoretical = black_scholes_greeks(
        25000, 25000, years, 0.06, 0.01, 0.20, "CE"
    )["price"]
    chain = pd.DataFrame([{
        "spot": 25000, "strike": 25000, "expiry": expiry,
        "option_type": "CE", "bid": theoretical - 0.05,
        "ask": theoretical + 0.05, "ltp": theoretical + 100,
    }])
    result = calculate_chain_greeks(
        chain, risk_free_rate=0.06, dividend_yield=0.01, now=NOW
    )
    assert result.loc[0, "bs_status"] == "OK"
    assert result.loc[0, "bs_market_mid"] == pytest.approx(theoretical)
    assert result.loc[0, "bs_iv"] == pytest.approx(0.20, abs=2e-5)
    assert result.loc[0, "bs_gamma"] > 0


def test_invalid_or_missing_quote_is_skipped_without_ltp_fallback():
    chain = pd.DataFrame([{
        "spot": 25000, "strike": 25000, "expiry": "2026-11-30",
        "option_type": "CE", "bid": 0, "ask": 10, "ltp": 9,
    }])
    result = calculate_chain_greeks(
        chain, risk_free_rate=0.06, dividend_yield=0.01, now=NOW
    )
    assert result.loc[0, "bs_status"] == "SKIPPED"
    assert result.loc[0, "bs_error"] == "INVALID_BID_ASK_OR_SPOT"
    assert math.isnan(result.loc[0, "bs_iv"])


def test_expired_contract_is_skipped():
    chain = pd.DataFrame([{
        "spot": 25000, "strike": 25000, "expiry": "2026-11-02",
        "option_type": "CE", "bid": 100, "ask": 101,
    }])
    result = calculate_chain_greeks(
        chain, risk_free_rate=0.06, dividend_yield=0.01, now=NOW
    )
    assert result.loc[0, "bs_status"] == "SKIPPED"
    assert result.loc[0, "bs_error"] == "EXPIRED_OR_ZERO_TTE"


def test_missing_columns_fail_fast():
    with pytest.raises(ValueError, match="MISSING_OPTION_CHAIN_COLUMNS"):
        calculate_chain_greeks(
            pd.DataFrame([{"spot": 1}]),
            risk_free_rate=0.06, dividend_yield=0.01, now=NOW,
        )


def test_broker_comparison_requires_explicit_iv_unit():
    chain = pd.DataFrame([{
        "spot": 25000, "strike": 25000, "expiry": "2026-11-30",
        "option_type": "CE", "bid": 250, "ask": 251,
        "iv": 20.0, "delta": 0.5, "gamma": 0.001,
        "theta": -5.0,
    }])
    calculated = calculate_chain_greeks(
        chain, risk_free_rate=0.06, dividend_yield=0.01, now=NOW
    )
    compared = compare_broker_greeks(
        calculated, broker_iv_is_percent=True
    )
    assert compared.loc[0, "iv_broker_minus_model"] == pytest.approx(
        0.20 - compared.loc[0, "bs_iv"]
    )
    assert "delta_broker_minus_model" in compared.columns
