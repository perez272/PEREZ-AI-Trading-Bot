import json
import sqlite3
from pathlib import Path


def test_tier1_pipeline_captures_analyzes_and_stores(tmp_path, monkeypatch):
    import src.tier1_pipeline_bridge as bridge
    import src.options_surge_engine as surge

    tier_db = tmp_path / "tier1.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    bridge.TIER1_DB = tier_db
    bridge.MEMORY_DB = memory_db
    surge.DB_PATH = memory_db

    tier = sqlite3.connect(tier_db)
    tier.execute(
        """CREATE TABLE raw_option_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_ts TEXT NOT NULL, symbol TEXT NOT NULL, option_type TEXT,
            instrument_key TEXT, contract TEXT, expiry TEXT, strike REAL,
            ltp REAL NOT NULL, features_json TEXT NOT NULL
        )"""
    )
    rich = {
        "ltp": 1.0, "volume": 1000, "oi": 5000, "oi_change": 250,
        "iv": 20.0, "delta": 0.2, "gamma": 0.01,
        "spot_ltp": 24300.0, "futures_ltp": 24305.0,
        "distance_to_spot_pct": 0.1, "minutes_to_expiry": 120.0,
        "expiry_bucket": "EXPIRY_DAY", "live_market_data": True,
        "bid": 0.99, "ask": 1.01, "spread_pct": 2.0,
    }
    tier.execute(
        "INSERT INTO raw_option_snapshots(observed_ts,symbol,option_type,instrument_key,contract,expiry,strike,ltp,features_json) VALUES(?,?,?,?,?,?,?,?,?)",
        ("2026-08-25T10:00:00+00:00", "NIFTY", "CE", "NFO|TEST", "NIFTYTESTCE", "2026-08-25", 24300, 1.0, json.dumps(rich)),
    )
    tier.commit()
    tier.close()

    result = bridge.process_new_observations()
    assert result["captured"] == 1
    assert result["processed"] == 1
    assert result["analyzed"] == 1

    con = sqlite3.connect(memory_db)
    assert con.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM tier1_pipeline_processed").fetchone()[0] == 1
    con.close()


def test_tier1_pipeline_is_idempotent(tmp_path):
    import src.tier1_pipeline_bridge as bridge
    import src.options_surge_engine as surge

    tier_db = tmp_path / "tier1.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    bridge.TIER1_DB = tier_db
    bridge.MEMORY_DB = memory_db
    surge.DB_PATH = memory_db

    tier = sqlite3.connect(tier_db)
    tier.execute(
        "CREATE TABLE raw_option_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, observed_ts TEXT, symbol TEXT, option_type TEXT, instrument_key TEXT, contract TEXT, expiry TEXT, strike REAL, ltp REAL, features_json TEXT)"
    )
    tier.execute(
        "INSERT INTO raw_option_snapshots(observed_ts,symbol,option_type,instrument_key,contract,expiry,strike,ltp,features_json) VALUES(?,?,?,?,?,?,?,?,?)",
        ("2026-08-25T10:00:00+00:00", "BANKNIFTY", "PE", "NFO|TEST2", "BANKTESTPE", "2026-08-25", 55000, 2.0, json.dumps({"ltp": 2.0, "volume": 100, "oi": 1000, "live_market_data": True})),
    )
    tier.commit(); tier.close()

    first = bridge.process_new_observations()
    second = bridge.process_new_observations()
    assert first["processed"] == 1
    assert second["processed"] == 0

    con = sqlite3.connect(memory_db)
    assert con.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    con.close()
