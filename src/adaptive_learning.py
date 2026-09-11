"""Outcome-driven pattern memory for PEREZ AI.

This is an advisory learning layer: it never changes risk limits, order mode,
entry window, or paper/live safety controls.  It learns from BOTH wins and
losses and only becomes influential after a pattern has enough observations.

Design:
- store the feature snapshot at every candidate/trade decision
- label closed outcomes with pnl, MFE and MAE when available
- bucket market regime + direction + momentum/volume/OI/liquidity state
- calculate a smoothed win-rate / expectancy for the pattern
- return a small bounded score adjustment and an explainable confidence
- use SQLite so learning survives process restarts
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/adaptive_trade_memory.sqlite3")
SCHEMA_VERSION = 1


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS pattern_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            event_key TEXT,
            symbol TEXT,
            option_type TEXT,
            pattern_key TEXT NOT NULL,
            features_json TEXT NOT NULL,
            outcome TEXT,
            pnl REAL,
            pnl_percent REAL,
            mfe REAL,
            mae REAL,
            exit_reason TEXT,
            resolved_ts TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pattern_key ON pattern_events(pattern_key);
        CREATE INDEX IF NOT EXISTS idx_event_key ON pattern_events(event_key);
        CREATE INDEX IF NOT EXISTS idx_outcome ON pattern_events(outcome);
        """
    )
    return c


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return default if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default


def _bucket(v: Any, cuts: tuple[float, ...]) -> str:
    x = _num(v)
    for i, cut in enumerate(cuts):
        if x < cut:
            return str(i)
    return str(len(cuts))


def _regime(candidate: dict[str, Any]) -> str:
    trend = _num(candidate.get("trend_score"))
    momentum = _num(candidate.get("momentum_score"))
    mtf = str(candidate.get("mtf_direction") or candidate.get("underlying_signal") or "").upper()
    if trend >= 10 and momentum >= 7 and mtf in {"BUY", "BULLISH", "CE", "CALL", "LONG"}:
        return "TREND_UP"
    if trend >= 10 and momentum >= 7 and mtf in {"SELL", "BEARISH", "PE", "PUT", "SHORT"}:
        return "TREND_DOWN"
    if abs(_num(candidate.get("percent_change"))) >= 5 and _num(candidate.get("volume_ratio")) >= 1.5:
        return "EXPANSION"
    if _num(candidate.get("spread_pct")) > 1.5 or _num(candidate.get("slippage_pct")) > 1.0:
        return "ILLIQUID"
    return "MIXED"


def pattern_features(candidate: dict[str, Any]) -> dict[str, Any]:
    """Keep a compact, leakage-safe snapshot of information known at entry."""
    return {
        "symbol": str(candidate.get("symbol") or candidate.get("underlying") or "").upper(),
        "option_type": str(candidate.get("option_type") or candidate.get("right") or "").upper(),
        "regime": _regime(candidate),
        "move_bucket": _bucket(candidate.get("percent_change"), (1, 2, 3, 5, 8, 12)),
        "momentum_bucket": _bucket(candidate.get("momentum_score"), (2, 5, 7, 9)),
        "trend_bucket": _bucket(candidate.get("trend_score"), (4, 8, 12)),
        "volume_bucket": _bucket(candidate.get("volume_ratio"), (0.75, 1.0, 1.5, 2.0, 3.0)),
        "oi_bucket": _bucket(candidate.get("oi_change_pct"), (-10, 0, 5, 10, 20)),
        "spread_bucket": _bucket(candidate.get("spread_pct"), (0.25, 0.5, 1.0, 1.5, 2.5)),
        "mtf": str(candidate.get("mtf_direction") or "").upper(),
        "source": str(candidate.get("data_source") or "").lower(),
    }


def pattern_key(candidate: dict[str, Any]) -> str:
    features = pattern_features(candidate)
    raw = json.dumps(features, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def remember_candidate(candidate: dict[str, Any], event_key: str = "") -> int:
    """Persist a candidate/trade snapshot once; returns row id."""
    c = _conn()
    key = pattern_key(candidate)
    existing = c.execute(
        "SELECT id FROM pattern_events WHERE event_key=? AND event_key<>'' LIMIT 1",
        (event_key,),
    ).fetchone() if event_key else None
    if existing:
        c.close()
        return int(existing["id"])
    now = datetime.now(timezone.utc).isoformat()
    cur = c.execute(
        """INSERT INTO pattern_events
           (created_ts,event_key,symbol,option_type,pattern_key,features_json)
           VALUES (?,?,?,?,?,?)""",
        (now, event_key, features_symbol(candidate), features_type(candidate), key,
         json.dumps(pattern_features(candidate), sort_keys=True)),
    )
    c.commit(); row_id = int(cur.lastrowid); c.close(); return row_id


def features_symbol(candidate: dict[str, Any]) -> str:
    return str(candidate.get("symbol") or candidate.get("underlying") or "").upper()


def features_type(candidate: dict[str, Any]) -> str:
    return str(candidate.get("option_type") or candidate.get("right") or "").upper()


def resolve_outcome(
    *,
    event_key: str = "",
    candidate: dict[str, Any] | None = None,
    pnl: float = 0.0,
    pnl_percent: float = 0.0,
    mfe: float | None = None,
    mae: float | None = None,
    exit_reason: str = "",
) -> bool:
    """Label the exact candidate row, or create one when only outcome data exists."""
    c = _conn()
    row = c.execute(
        "SELECT id FROM pattern_events WHERE event_key=? ORDER BY id DESC LIMIT 1",
        (event_key,),
    ).fetchone() if event_key else None
    if row is None and candidate is not None:
        remember_candidate(candidate, event_key)
        row = c.execute(
            "SELECT id FROM pattern_events WHERE event_key=? ORDER BY id DESC LIMIT 1",
            (event_key,),
        ).fetchone()
    if row is None:
        c.close(); return False
    outcome = "WIN" if _num(pnl) > 0 else ("LOSS" if _num(pnl) < 0 else "FLAT")
    c.execute(
        """UPDATE pattern_events SET outcome=?,pnl=?,pnl_percent=?,mfe=?,mae=?,
           exit_reason=?,resolved_ts=? WHERE id=?""",
        (outcome, _num(pnl), _num(pnl_percent), None if mfe is None else _num(mfe),
         None if mae is None else _num(mae), str(exit_reason or ""),
         datetime.now(timezone.utc).isoformat(), int(row["id"])),
    )
    c.commit(); c.close(); return True


def learning_signal(candidate: dict[str, Any], min_samples: int = 5) -> dict[str, Any]:
    """Return an explainable, bounded pattern adjustment.

    Positive expectancy gets a bonus; negative expectancy gets a penalty.
    Small samples remain neutral, preventing cold-start self-deception.
    """
    key = pattern_key(candidate)
    c = _conn()
    row = c.execute(
        """SELECT COUNT(*) n,
                  SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) wins,
                  SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                  AVG(CASE WHEN outcome IS NOT NULL THEN pnl_percent END) avg_pnl,
                  AVG(CASE WHEN outcome IS NOT NULL THEN mfe END) avg_mfe,
                  AVG(CASE WHEN outcome IS NOT NULL THEN mae END) avg_mae
           FROM pattern_events WHERE pattern_key=? AND outcome IS NOT NULL""",
        (key,),
    ).fetchone()
    c.close()
    n = int(row["n"] or 0)
    if n < min_samples:
        return {"adjustment": 0.0, "confidence": 0.0, "samples": n, "status": "WARMING_UP", "pattern_key": key}
    wins = int(row["wins"] or 0); losses = int(row["losses"] or 0)
    avg_pnl = _num(row["avg_pnl"])
    win_rate = wins / max(wins + losses, 1)
    # Bayesian smoothing around 50% plus expectancy; cap at +/-8 so memory
    # cannot overpower the existing signal/gates.
    smoothed = (wins + 2.0) / (wins + losses + 4.0)
    edge = (smoothed - 0.5) * 16.0
    expectancy = max(-4.0, min(4.0, avg_pnl))
    adjustment = round(max(-8.0, min(8.0, edge + expectancy)), 2)
    confidence = round(min(1.0, n / 30.0) * (0.5 + abs(smoothed - 0.5)), 3)
    return {
        "adjustment": adjustment,
        "confidence": confidence,
        "samples": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "avg_pnl_percent": round(avg_pnl, 4),
        "avg_mfe": round(_num(row["avg_mfe"]), 4),
        "avg_mae": round(_num(row["avg_mae"]), 4),
        "status": "LEARNED",
        "pattern_key": key,
    }


def memory_stats() -> dict[str, Any]:
    c = _conn()
    row = c.execute("SELECT COUNT(*) total, SUM(outcome='WIN') wins, SUM(outcome='LOSS') losses FROM pattern_events").fetchone()
    patterns = c.execute("SELECT COUNT(DISTINCT pattern_key) FROM pattern_events WHERE outcome IS NOT NULL").fetchone()[0]
    c.close()
    return {"total_events": int(row["total"] or 0), "wins": int(row["wins"] or 0), "losses": int(row["losses"] or 0), "learned_patterns": int(patterns or 0), "schema_version": SCHEMA_VERSION}
