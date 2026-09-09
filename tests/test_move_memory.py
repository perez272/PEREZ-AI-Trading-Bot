import json
import sqlite3

import src.move_memory as mm


def make_db(tmp_path):
    db = tmp_path / "move_memory.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE move_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            option_type TEXT,
            contract TEXT,
            expiry TEXT,
            strike REAL,
            threshold REAL NOT NULL,
            baseline_ltp REAL NOT NULL,
            ltp REAL NOT NULL,
            move_pct REAL NOT NULL,
            observed_ts TEXT NOT NULL,
            features_json TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    mm.DB_PATH = db
    return db


def insert_event(
    db,
    *,
    event_key,
    threshold,
    observed_ts,
    symbol="NIFTY",
    option_type="CE",
    expiry="2026-09-15",
    strike=25000,
    move_pct=20,
):
    features = {
        "symbol": symbol,
        "option_type": option_type,
        "percent_change": move_pct,
        "move_pct": move_pct,
        "trend_score": 10,
        "momentum_score": 8,
        "vwap_score": 7,
        "volume_score": 8,
        "oi_score": 8,
        "oi_change_score": 8,
        "iv_score": 4,
        "liquidity_score": 6,
        "spread_pct": 1,
        "slippage_pct": 0,
    }

    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO move_events(
            event_key, symbol, option_type, contract, expiry, strike,
            threshold, baseline_ltp, ltp, move_pct, observed_ts, features_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_key,
            symbol,
            option_type,
            f"{symbol} {strike} {option_type}",
            expiry,
            strike,
            threshold,
            100,
            100 + move_pct,
            move_pct,
            observed_ts,
            json.dumps(features),
        ),
    )
    conn.commit()
    conn.close()


def candidate():
    return {
        "symbol": "NIFTY",
        "option_type": "CE",
        "percent_change": 20,
        "trend_score": 10,
        "momentum_score": 8,
        "vwap_score": 7,
        "volume_score": 8,
        "oi_score": 8,
        "oi_change_score": 8,
        "iv_score": 4,
        "liquidity_score": 6,
        "spread_pct": 1,
        "slippage_pct": 0,
    }


def test_threshold_rows_from_one_observation_count_as_one_match(tmp_path):
    db = make_db(tmp_path)

    for threshold in (5, 10, 15, 20):
        insert_event(
            db,
            event_key=f"same-observation-{threshold}",
            threshold=threshold,
            observed_ts="2026-09-09T10:30:00+05:30",
        )

    result = mm.similarity_bonus(candidate())

    assert result["matches"] == 1
    assert result["best_target"] == 20


def test_highest_threshold_is_retained_for_same_observation(tmp_path):
    db = make_db(tmp_path)

    insert_event(
        db,
        event_key="low",
        threshold=5,
        observed_ts="2026-09-09T10:31:00+05:30",
    )
    insert_event(
        db,
        event_key="high",
        threshold=15,
        observed_ts="2026-09-09T10:31:00+05:30",
    )

    result = mm.similarity_bonus(candidate())

    assert result["matches"] == 1
    assert result["best_target"] == 15


def test_different_observation_minutes_remain_distinct(tmp_path):
    db = make_db(tmp_path)

    insert_event(
        db,
        event_key="event-a",
        threshold=10,
        observed_ts="2026-09-09T10:31:00+05:30",
    )
    insert_event(
        db,
        event_key="event-b",
        threshold=10,
        observed_ts="2026-09-09T10:32:00+05:30",
    )

    result = mm.similarity_bonus(candidate())

    assert result["matches"] == 2


def test_symbol_and_option_type_are_filtered(tmp_path):
    db = make_db(tmp_path)

    insert_event(
        db,
        event_key="nifty-ce",
        threshold=10,
        observed_ts="2026-09-09T10:33:00+05:30",
        symbol="NIFTY",
        option_type="CE",
    )
    insert_event(
        db,
        event_key="banknifty-ce",
        threshold=10,
        observed_ts="2026-09-09T10:33:00+05:30",
        symbol="BANKNIFTY",
        option_type="CE",
    )
    insert_event(
        db,
        event_key="nifty-pe",
        threshold=10,
        observed_ts="2026-09-09T10:33:00+05:30",
        symbol="NIFTY",
        option_type="PE",
    )

    result = mm.similarity_bonus(candidate())

    assert result["matches"] == 1

def test_opposite_move_direction_has_zero_similarity():
    historical = {
        "percent_change": 23.0,
        "volume": 33000000.0,
        "oi": 8700000.0,
        "bid": 1.34,
        "ask": 1.41,
        "iv": 18.2,
        "delta": 0.49,
        "gamma": 0.01,
        "theta": -2.1,
        "vega": 1.02,
    }

    same_direction = {
        "percent_change": 23.0,
        "volume": 33000000.0,
        "open_interest": 8700000.0,
        "best_bid": 1.34,
        "best_ask": 1.41,
        "iv": 18.2,
        "delta": 0.49,
        "gamma": 0.01,
        "theta": -2.1,
        "vega": 1.02,
    }

    opposite_direction = dict(same_direction)
    opposite_direction["percent_change"] = -23.0

    assert mm._similarity(same_direction, historical) == 1.0
    assert mm._similarity(opposite_direction, historical) == 0.0
