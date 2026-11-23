from datetime import datetime
from zoneinfo import ZoneInfo

from src.expiry_oi_shadow import analyze_chain, expiry_class, record_chain_snapshot, latest_observations

IST = ZoneInfo("Asia/Kolkata")


def _chain(expiry="2026-11-22"):
    chain = [
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
    for strike in (24900, 24950, 25100):
        chain.append({
            "expiry": expiry, "strike_price": strike, "underlying_spot_price": 25010,
            "call_options": {"instrument_key": f"CE{strike}", "market_data": {"ltp": 70, "oi": 100, "volume": 50}},
            "put_options": {"instrument_key": f"PE{strike}", "market_data": {"ltp": 75, "oi": 100, "volume": 50}},
        })
    return chain


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
    assert latest_observations(db, now="2026-11-22T10:00:15+05:30")[0]["observed_at"] == "2026-11-22T10:00:15+05:30"



def test_clean_up_breakout_requires_two_snapshots_beyond_oi_wall_and_bullish_oi():
    chain = _chain()
    for row in chain:
        row["underlying_spot_price"] = 25100
    previous = {}
    for row in chain:
        for side in ("CE", "PE"):
            option = row["call_options" if side == "CE" else "put_options"]
            previous[option["instrument_key"]] = {
                "oi": option["market_data"]["oi"] + (100 if side == "CE" else -100),
                "ltp": option["market_data"]["ltp"] - (5 if side == "CE" else 0),
                "spot": 25080, "observed_at": "2026-11-22T10:00:00+05:30",
            }
    result = analyze_chain("NIFTY", chain, "2026-11-22T10:00:15+05:30", previous)
    assert result["oi_direction"] == "BULLISH_OI_PATTERN"
    assert result["breakout_status"] == "UP_BREAKOUT_CONFIRMED"
    assert result["breakout_confirmed"] is True
    assert result["safety"] == "OBSERVATION_ONLY"


def test_breakout_is_not_confirmed_without_prior_spot_beyond_oi_wall():
    chain = _chain()
    for row in chain:
        row["underlying_spot_price"] = 25100
    previous = {}
    for row in chain:
        for side in ("CE", "PE"):
            option = row["call_options" if side == "CE" else "put_options"]
            previous[option["instrument_key"]] = {
                "oi": option["market_data"]["oi"] + (100 if side == "CE" else -100),
                "ltp": option["market_data"]["ltp"] - (5 if side == "CE" else 0),
                "spot": 25060, "observed_at": "2026-11-22T10:00:00+05:30",
            }
    result = analyze_chain("NIFTY", chain, "2026-11-22T10:00:15+05:30", previous)
    assert result["oi_direction"] == "BULLISH_OI_PATTERN"
    assert result["breakout_status"] == "NOT_CONFIRMED"
    assert result["breakout_confirmed"] is False



def test_candidate_exposes_real_gamma_and_lot_size_when_provider_supplies_them():
    chain = _chain()
    chain[0]["call_options"]["option_greeks"]["gamma"] = 0.031
    chain[0]["call_options"]["lot_size"] = 25
    result = analyze_chain("NIFTY", chain, "2026-11-22T10:00:00+05:30")
    candidate = next(item for item in result["candidates"]
                     if item["side"] == "CE" and item["strike"] == 25000)
    assert candidate["gamma"] == 0.031
    assert candidate["lot_size"] == 25



def test_rejects_chain_without_underlying_spot_or_strike_coverage():
    chain = _chain()
    for row in chain:
        row["underlying_spot_price"] = None
    result = analyze_chain("NIFTY", chain, "2026-11-22T10:00:00+05:30")
    assert result["data_quality_status"] == "REJECTED"
    assert "MISSING_UNDERLYING_SPOT" in result["data_quality_reasons"]
    assert result["highest_combined_oi_strike"] is None
    assert result["max_pain_strike"] is None


def test_expired_chain_is_rejected_before_persistence(tmp_path):
    import pytest

    db = tmp_path / "shadow.sqlite3"
    with pytest.raises(ValueError, match="EXPIRED_CONTRACTS"):
        record_chain_snapshot("NIFTY", _chain("2026-11-21"),
                              "2026-11-22T10:00:00+05:30", db)
    assert not db.exists()


def test_latest_observations_excludes_stale_records(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_chain_snapshot("NIFTY", _chain(),
                          "2026-11-22T10:00:00+05:30", db)
    assert latest_observations(
        db, now="2026-11-22T10:03:00+05:30", max_age_seconds=120
    ) == []


def test_latest_observations_excludes_legacy_unvalidated_rows(tmp_path):
    import json
    import sqlite3

    db = tmp_path / "shadow.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL)")
        conn.execute("INSERT INTO observations(symbol,observed_at,payload_json) VALUES (?,?,?)",
                     ("NIFTY", "2026-11-22T10:00:00+05:30",
                      json.dumps({"symbol": "NIFTY", "observed_at": "2026-11-22T10:00:00+05:30",
                                  "expiry": "2026-11-22", "oi_chain_complete": True})))
    assert latest_observations(
        db, now="2026-11-22T10:00:10+05:30"
    ) == []
