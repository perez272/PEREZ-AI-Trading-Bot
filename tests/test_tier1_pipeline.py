import concurrent.futures
import json
import sqlite3


def _setup_raw(tier_db, symbol="NIFTY", contract="NIFTYTESTCE", ltp=1.0):
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
        "ltp": ltp, "volume": 1000, "oi": 5000, "oi_change": 250,
        "iv": 20.0, "delta": 0.2, "gamma": 0.01,
        "spot_ltp": 24300.0, "futures_ltp": 24305.0,
        "distance_to_spot_pct": 0.1, "minutes_to_expiry": 120.0,
        "expiry_bucket": "EXPIRY_DAY", "live_market_data": True,
        "bid": max(ltp - 0.01, 0.01), "ask": ltp + 0.01, "spread_pct": 2.0,
    }
    tier.execute(
        "INSERT INTO raw_option_snapshots(observed_ts,symbol,option_type,instrument_key,contract,expiry,strike,ltp,features_json) VALUES(?,?,?,?,?,?,?,?,?)",
        ("2026-08-25T10:00:00+00:00", symbol, "CE", f"NFO|{contract}", contract, "2026-08-25", 24300, ltp, json.dumps(rich)),
    )
    tier.commit()
    tier.close()


def test_tier1_pipeline_captures_analyzes_and_stores(tmp_path, monkeypatch):
    import src.tier1_pipeline_bridge as bridge
    import src.options_surge_engine as surge

    tier_db = tmp_path / "tier1.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    bridge.TIER1_DB = tier_db
    bridge.MEMORY_DB = memory_db
    surge.DB_PATH = memory_db

    _setup_raw(tier_db)
    result = bridge.process_new_observations()
    assert result["captured"] == 1
    assert result["processed"] == 1
    assert result["analyzed"] == 1

    con = sqlite3.connect(memory_db)
    assert con.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    con.close()

    tier = sqlite3.connect(tier_db)
    assert tier.execute("SELECT COUNT(*) FROM tier1_pipeline_processed").fetchone()[0] == 1
    assert tier.execute("SELECT source_id FROM tier1_pipeline_processed").fetchone()[0] == 1
    tier.close()

    memory = sqlite3.connect(memory_db)
    assert memory.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tier1_pipeline_processed'").fetchone() is None
    memory.close()


def test_tier1_pipeline_is_idempotent(tmp_path):
    import src.tier1_pipeline_bridge as bridge
    import src.options_surge_engine as surge

    tier_db = tmp_path / "tier1.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    bridge.TIER1_DB = tier_db
    bridge.MEMORY_DB = memory_db
    surge.DB_PATH = memory_db

    _setup_raw(tier_db, symbol="BANKNIFTY", contract="BANKTESTPE", ltp=2.0)
    first = bridge.process_new_observations()
    second = bridge.process_new_observations()
    assert first["processed"] == 1
    assert second["processed"] == 0

    con = sqlite3.connect(memory_db)
    assert con.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    con.close()

    tier = sqlite3.connect(tier_db)
    assert tier.execute("SELECT COUNT(*) FROM tier1_pipeline_processed").fetchone()[0] == 1
    tier.close()


def test_surge_failure_still_writes_tier1_marker(tmp_path, monkeypatch):
    import src.tier1_pipeline_bridge as bridge
    import src.options_surge_engine as surge

    tier_db = tmp_path / "tier1.sqlite3"
    memory_db = tmp_path / "memory.sqlite3"
    bridge.TIER1_DB = tier_db
    bridge.MEMORY_DB = memory_db
    surge.DB_PATH = memory_db
    _setup_raw(tier_db)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bridge, "observe_option", fail)
    result = bridge.process_new_observations()
    assert result["processed"] == 1

    tier = sqlite3.connect(tier_db)
    row = tier.execute("SELECT source_id, processing_error FROM tier1_pipeline_processed").fetchone()
    assert row[0] == 1
    assert "database is locked" in row[1]
    tier.close()


def test_tier1_sqlite_concurrent_memory_writes(tmp_path):
    """Concurrent surge writers must serialize instead of failing with SQLITE_BUSY."""
    import src.options_surge_engine as surge

    memory_db = tmp_path / "memory.sqlite3"
    surge.DB_PATH = memory_db

    def write(i):
        return surge.observe_option(
            {"symbol": "NIFTY", "option_type": "CE", "contract": f"CONCURRENT{i}", "expiry": "2026-08-25", "strike": 24300, "ltp": 10.0},
            {"symbol": "NIFTY", "option_type": "CE", "contract": f"CONCURRENT{i}", "expiry": "2026-08-25", "strike": 24300, "ltp": 10.0,
             "market_data": {"volume": 1000, "oi": 5000}, "live_market_data": True},
            regime="concurrency_test",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(8)))

    con = sqlite3.connect(memory_db)
    assert con.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0] == 8
    con.close()
