"""Persistent pattern memory for large Tier-1 index option moves.

This is an evidence store, not an automatic black-box trader.  It records the
indicator state observed when an option reaches +5/+10/+15/+20% and uses prior
successful states as a similarity bonus on future scans.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/tier1_option_moves.sqlite3")
TARGETS = (5.0, 10.0, 15.0, 20.0)
FEATURES = (
    "percent_change", "trend_score", "momentum_score", "vwap_score",
    "volume_score", "oi_score", "oi_change_score", "iv_score",
    "liquidity_score", "spread_pct", "slippage_pct", "atr_pct",
    "rsi", "rsi_slope", "ema_gap_pct", "breakout_strength", "body_strength",
    "volume_ratio", "spot_change_pct", "spot_score", "mtf_aligned",
)


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS move_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            symbol TEXT NOT NULL,
            option_type TEXT NOT NULL,
            expiry TEXT,
            contract TEXT,
            target_pct REAL NOT NULL,
            """ + ",".join(f"{f} REAL" for f in FEATURES) + ", UNIQUE(symbol, contract, target_pct, ts_utc))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_move_target ON move_events(target_pct)")
    conn.commit()
    return conn


def _num(v: Any) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def record_move(candidate: dict[str, Any]) -> list[float]:
    """Record each newly crossed target. Returns targets written this call."""
    pct = _num(candidate.get("percent_change"))
    if pct <= 0:
        return []
    crossed = [target for target in TARGETS if pct >= target]
    if not crossed:
        return []
    conn = _connect()
    written = []
    ts = datetime.now(timezone.utc).isoformat()
    values = [_num(candidate.get(f)) for f in FEATURES]
    for target in crossed:
        row = [
            ts, str(candidate.get("symbol", "")), str(candidate.get("option_type", "")),
            str(candidate.get("expiry", "")), str(candidate.get("contract", "")), target, *values,
        ]
        conn.execute(
            f"INSERT OR IGNORE INTO move_events (ts_utc,symbol,option_type,expiry,contract,target_pct,{','.join(FEATURES)}) VALUES ({','.join('?' for _ in row)})",
            row,
        )
        if conn.total_changes:
            written.append(target)
    conn.commit()
    conn.close()
    return written


def _similarity(candidate: dict[str, Any], row: sqlite3.Row) -> float:
    # Bounded, scale-aware similarity. No future price information is used.
    scales = {
        "percent_change": 10, "trend_score": 15, "momentum_score": 10, "vwap_score": 7,
        "volume_score": 8, "oi_score": 10, "oi_change_score": 8, "iv_score": 5,
        "liquidity_score": 7, "spread_pct": 2, "slippage_pct": 2, "atr_pct": 2,
        "rsi": 20, "rsi_slope": 5, "ema_gap_pct": 2, "breakout_strength": 2,
        "body_strength": 1, "volume_ratio": 2, "spot_change_pct": 2, "spot_score": 100,
        "mtf_aligned": 1,
    }
    distance = 0.0
    weight = 0.0
    for feature in FEATURES:
        scale = scales.get(feature, 1)
        a = _num(candidate.get(feature))
        b = _num(row[feature])
        distance += min(abs(a - b) / max(scale, 1e-9), 3.0)
        weight += 1.0
    return max(0.0, 1.0 - distance / max(weight * 1.5, 1.0))


def similarity_bonus(candidate: dict[str, Any], minimum_target: float = 5.0) -> dict[str, Any]:
    """Return a bounded score bonus based only on previously recorded moves."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM move_events WHERE target_pct >= ? ORDER BY id DESC LIMIT 500",
        (minimum_target,),
    ).fetchall()
    conn.close()
    if not rows:
        return {"bonus": 0.0, "matches": 0, "best_target": 0.0}
    scored = [(round(_similarity(candidate, row), 4), float(row["target_pct"])) for row in rows]
    scored.sort(reverse=True)
    best = scored[:5]
    strength = sum(score for score, _ in best) / len(best)
    bonus = min(12.0, round(strength * 12.0, 2)) if strength >= 0.45 else 0.0
    return {"bonus": bonus, "matches": sum(1 for score, _ in scored if score >= 0.45), "best_target": max((target for score, target in best if score >= 0.45), default=0.0)}


def memory_stats() -> dict[str, Any]:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM move_events").fetchone()[0]
    by_target = {int(target): count for target, count in conn.execute("SELECT target_pct, COUNT(*) FROM move_events GROUP BY target_pct")}
    conn.close()
    return {"total_events": total, "by_target": by_target, "database": str(DB_PATH)}
