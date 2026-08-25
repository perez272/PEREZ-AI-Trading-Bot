"""End-to-end Tier-1 research pipeline bridge.

The observer owns broker ingestion. This bridge guarantees that every raw
valid option observation is forwarded into the richer PEREZ memory/surge path,
even if the optional memory callback inside the observer fails. It is strictly
observational and has no order/execution authority.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.explosive_move_detector import detect_explosive_move
from src.expiry_learning_engine import learn_from_surge
from src.options_surge_engine import observe_option

ROOT = Path(os.getenv("PEREZ_AI_ROOT", "/home/ubuntu/PEREZ-AI-Trading-Bot"))
TIER1_DB = Path(os.getenv("TIER1_OPTION_MEMORY", str(ROOT / "data/memory/tier1_option_moves.sqlite3")))
MEMORY_DB = Path(os.getenv("PEREZ_AI_MEMORY_DB", str(ROOT / "data/memory/perez_ai_memory.db")))
BATCH_LIMIT = int(os.getenv("TIER1_PIPELINE_BATCH", "5000"))


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _option_from_rich(row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rich = json.loads(row["features_json"] or "{}")
    greeks = {k: rich.get(k) for k in ("iv", "delta", "gamma", "theta", "vega", "rho") if rich.get(k) is not None}
    market = {
        "instrument_key": row["instrument_key"],
        "trading_symbol": row["contract"],
        "market_data": rich,
        "option_greeks": greeks,
        "live_market_data": True,
    }
    candidate = {
        "symbol": row["symbol"], "option_type": row["option_type"], "contract": row["contract"],
        "expiry": row["expiry"], "strike": row["strike"], "ltp": row["ltp"],
        "spot_ltp": rich.get("spot_ltp"), "futures_ltp": rich.get("futures_ltp"),
        "distance_to_spot_pct": rich.get("distance_to_spot_pct"),
        "minutes_to_expiry": rich.get("minutes_to_expiry"), "expiry_bucket": rich.get("expiry_bucket"),
        "live_market_data": True,
    }
    return candidate, market, rich


def _history(tier: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    rows = tier.execute(
        "SELECT instrument_key,contract,features_json FROM raw_option_snapshots "
        "WHERE instrument_key=? AND id<? ORDER BY id DESC LIMIT 6",
        (row["instrument_key"], row["id"]),
    ).fetchall()
    result = []
    for old in reversed(rows):
        rich = json.loads(old["features_json"] or "{}")
        greeks = {k: rich.get(k) for k in ("iv", "delta", "gamma", "theta", "vega", "rho") if rich.get(k) is not None}
        result.append({"instrument_key": old["instrument_key"], "market_data": rich, "option_greeks": greeks})
    return result


def _ensure_pipeline_table(tier: sqlite3.Connection) -> None:
    """The processed marker belongs to the Tier-1 source database."""
    tier.execute(
        """CREATE TABLE IF NOT EXISTS tier1_pipeline_processed (
            source_id INTEGER PRIMARY KEY,
            processed_ts TEXT NOT NULL,
            analysis_score REAL,
            early_signal INTEGER NOT NULL DEFAULT 0,
            surge_events INTEGER NOT NULL DEFAULT 0,
            expiry_learning_json TEXT
        )"""
    )


def _ensure_memory_tables(memory: sqlite3.Connection) -> None:
    """Create only the bridge-owned memory tables needed by isolated tests."""
    memory.execute(
        """CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, signal TEXT,
            score REAL, options_score REAL, regime TEXT, features_json TEXT
        )"""
    )
    memory.execute(
        """CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, category TEXT,
            lesson TEXT, evidence_json TEXT
        )"""
    )


def process_new_observations(limit: int = BATCH_LIMIT) -> dict[str, int]:
    """Process every unprocessed raw Tier-1 snapshot exactly once."""
    processed = analyzed = early = surge = lessons = 0
    with _connect(TIER1_DB) as tier, _connect(MEMORY_DB) as memory:
        _ensure_pipeline_table(tier)
        _ensure_memory_tables(memory)
        rows = tier.execute(
            """SELECT r.* FROM raw_option_snapshots r
               LEFT JOIN tier1_pipeline_processed p ON p.source_id=r.id
               WHERE p.source_id IS NULL ORDER BY r.id LIMIT ?""",
            (int(limit),),
        ).fetchall()

        for row in rows:
            candidate, option, rich = _option_from_rich(row)
            history = _history(tier, row)
            signal = detect_explosive_move(row["symbol"], row["option_type"], option, history)
            analyzed += 1
            if signal and signal.early:
                early += 1
                rich["precursor_score"] = signal.precursor_score
                rich["precursor_reasons"] = list(signal.reasons)
                rich["move_1m_pct"] = signal.move_1m_pct
                rich["move_3m_pct"] = signal.move_3m_pct
                rich["move_5m_pct"] = signal.move_5m_pct
                rich["acceleration_pct_per_min2"] = signal.acceleration_pct_per_min2
                rich["volume_ratio"] = signal.volume_ratio
                rich["oi_change_pct"] = signal.oi_change_pct
                rich["iv_change_pct"] = signal.iv_change_pct

            events = observe_option(candidate, option, regime="tier1_observation")
            surge += len(events)
            expiry_evidence = []
            for event in events:
                evidence = learn_from_surge(event)
                event["expiry_learning"] = evidence
                expiry_evidence.append(evidence)
                lessons += 1
                memory.execute(
                    "INSERT INTO lessons(ts,category,lesson,evidence_json) VALUES(?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), "OPTIONS_SURGE",
                     "Tier-1 surge captured with precursor and expiry context; retained for outcome learning.",
                     json.dumps(event, default=str)),
                )

            features = dict(rich)
            features["pipeline_source_id"] = row["id"]
            features["analysis"] = {
                "precursor_score": getattr(signal, "precursor_score", 0.0) if signal else 0.0,
                "early": bool(signal and signal.early),
                "reasons": list(signal.reasons) if signal else [],
                "surge_events": len(events),
            }
            memory.execute(
                "INSERT INTO observations(ts,symbol,signal,score,options_score,regime,features_json) VALUES(?,?,?,?,?,?,?)",
                (row["observed_ts"], row["symbol"],
                 "EARLY_EXPLOSIVE" if signal and signal.early else "OBSERVATION",
                 float(getattr(signal, "precursor_score", 0.0) if signal else 0.0),
                 float(getattr(signal, "score", 0.0) if signal else 0.0),
                 "tier1_observation", json.dumps(features, default=str)),
            )
            tier.execute(
                """INSERT INTO tier1_pipeline_processed
                   (source_id,processed_ts,analysis_score,early_signal,surge_events,expiry_learning_json)
                   VALUES(?,?,?,?,?,?)""",
                (row["id"], datetime.now(timezone.utc).isoformat(),
                 float(getattr(signal, "precursor_score", 0.0) if signal else 0.0),
                 int(bool(signal and signal.early)), len(events), json.dumps(expiry_evidence, default=str)),
            )
            processed += 1
        tier.commit()
        memory.commit()

    return {"captured": len(rows), "processed": processed, "analyzed": analyzed,
            "early_signals": early, "surge_events": surge, "lessons": lessons}


def pipeline_status() -> dict[str, int]:
    with _connect(TIER1_DB) as tier, _connect(MEMORY_DB) as memory:
        _ensure_pipeline_table(tier)
        _ensure_memory_tables(memory)
        raw = tier.execute("SELECT COUNT(*) FROM raw_option_snapshots").fetchone()[0]
        processed = tier.execute("SELECT COUNT(*) FROM tier1_pipeline_processed").fetchone()[0]
        snapshots = memory.execute("SELECT COUNT(*) FROM option_snapshots").fetchone()[0]
        surges = memory.execute("SELECT COUNT(*) FROM option_surge_events").fetchone()[0]
        observations = memory.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        lessons = memory.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    return {"captured": int(raw), "processed": int(processed), "snapshots": int(snapshots),
            "surge_events": int(surges), "observations": int(observations), "lessons": int(lessons)}
