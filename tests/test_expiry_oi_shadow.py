from datetime import datetime
from zoneinfo import ZoneInfo

from src.expiry_oi_shadow import analyze_chain, expiry_class, record_chain_snapshot, latest_observations

IST = ZoneInfo("Asia/Kolkata")


def _chain(expiry="2026-11-22"):
    return [
        {"expiry": expiry, "strike_price": 25000, "underlying_spot_price": 25010,
         "call_options": {"instrument_key": "CE25000", "market_data": {"ltp": 100, "oi": 1000, "volume": 500},
                          "option_greeks": {"delta": 0.52}},
         "put_options": {"instrument_key": "PE25000", "market_data": {"ltp": 90, "oi": 1200, "volume": 450},
                         "option_greeks": {"delta": -0.48}}},
        {"expiry": expiry, "strike_price": 25050, "underlying_spot_price": 25010,
         "call_options": {"instrument_key": "CE25050", "market_data": {"ltp": 80, "oi": 1500, "volume": 600},
                          "option_greeks": {"delta": 0.42}},
         "put_options": {"instrument_key": "PE25050", "market_data": {"ltp": 110, "oi": 900, "volume": 400},
                         "option_greeks": {"delta": -0.58}}},
    ]


def test_expiry_class_uses_actual_contract_date():
    now = datetime(2026, 11, 22, 10, 0, tzinfo=IST)
    assert expiry_class("2026-11-22", now)["bucket"] == "0DTE"
    assert expiry_class("2026-11-23", now)["bucket"] == "1DTE"
    assert expiry_class("2026-11-24", now)["bucket"] == "OTHER"


def test_delta_band_and_atm_near_itm_candidates_are_observation_only():
    result = analyze_chain("NIFTY", _chain(), "2026-11-22T10:00:00+05:30")
    assert result["expiry_bucket"] == "0DTE"
    assert result["candidates"]
    assert any(item["delta_in_band"] is True for item in result["candidates"])
    assert result["safety"] == "OBSERVATION_ONLY"


def test_first_snapshot_does_not_invent_oi_change():
    result = analyze_chain("SENSEX", _chain(), "2026-11-22T10:00:00+05:30")
    assert result["oi_direction"] == "NO_CONFIRMED_OI_PATTERN"
    assert all(item["oi_change"] is None for item in result["oi_evidence"])


def test_stale_snapshot_is_not_used_for_oi_confirmation():
    previous = {"CE25000": {"oi": 1000, "ltp": 100, "spot": 25000,
                            "observed_at": "2026-11-22T09:55:00+05:30"}}
    result = analyze_chain("NIFTY", _chain(), "2026-11-22T10:00:00+05:30", previous)
    assert next(x for x in result["oi_evidence"] if x["side"] == "CE" and x["strike"] == 25000)["oi_change"] is None


def test_bullish_oi_pattern_requires_spot_rise_call_unwind_and_put_build():
    chain = _chain()
    previous = {}
    for row in chain:
        for side in ("CE", "PE"):
            option = row["call_options" if side == "CE" else "put_options"]
            previous[option["instrument_key"]] = {
                "oi": option["market_data"]["oi"] + (100 if side == "CE" else -100),
                "ltp": option["market_data"]["ltp"] - (5 if side == "CE" else 0),
                "spot": 24990, "observed_at": "2026-11-22T10:00:00+05:30",
            }
    assert analyze_chain("NIFTY", chain, "2026-11-22T10:00:15+05:30", previous)["oi_direction"] == "BULLISH_OI_PATTERN"


def test_bearish_oi_pattern_requires_spot_fall_put_unwind_and_call_build():
    chain = _chain()
    previous = {}
    for row in chain:
        for side in ("CE", "PE"):
            option = row["call_options" if side == "CE" else "put_options"]
            previous[option["instrument_key"]] = {
                "oi": option["market_data"]["oi"] + (-100 if side == "CE" else 100),
                "ltp": option["market_data"]["ltp"] - (5 if side == "PE" else 0),
                "spot": 25030, "observed_at": "2026-11-22T10:00:00+05:30",
            }
    assert analyze_chain("NIFTY", chain, "2026-11-22T10:00:15+05:30", previous)["oi_direction"] == "BEARISH_OI_PATTERN"


def test_incomplete_oi_chain_does_not_claim_max_pain_or_pinning_strike():
    chain = _chain()
    chain[0]["put_options"]["market_data"]["oi"] = None
    result = analyze_chain("NIFTY", chain, "2026-11-22T12:00:00+05:30")
    assert result["oi_chain_complete"] is False
    assert result["highest_combined_oi_strike"] is None
    assert result["max_pain_strike"] is None
    assert result["pinning_candidate"] is False


def test_midday_pinning_requires_proximity_to_highest_combined_oi_strike():
    result = analyze_chain("NIFTY", _chain(), "2026-11-22T12:00:00+05:30")
    assert result["pinning_window"] is True
    assert result["highest_combined_oi_strike"] == 25050
    assert result["max_pain_strike"] == 25000
    assert result["max_pain_strike"] != result["highest_combined_oi_strike"]
    assert result["pinning_candidate"] is False


def test_late_0dte_cutoff_is_observation_only():
    result = analyze_chain("NIFTY", _chain(), "2026-11-22T14:15:00+05:30")
    assert result["late_0dte_cutoff"] is True
    assert result["safety"] == "OBSERVATION_ONLY"


def test_snapshot_persists_and_exposes_latest_record(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    chain = _chain()
    first = record_chain_snapshot("NIFTY", chain, "2026-11-22T10:00:00+05:30", db)
    assert first["oi_direction"] == "NO_CONFIRMED_OI_PATTERN"
    chain[0]["call_options"]["market_data"]["oi"] = 900
    chain[0]["call_options"]["market_data"]["ltp"] = 110
    second = record_chain_snapshot("NIFTY", chain, "2026-11-22T10:00:15+05:30", db)
    assert second["oi_direction"] == "NO_CONFIRMED_OI_PATTERN"
    assert latest_observations(db)[0]["observed_at"] == "2026-11-22T10:00:15+05:30"
