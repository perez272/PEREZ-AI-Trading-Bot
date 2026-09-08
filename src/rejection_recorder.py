"""Canonical rejection evidence persistence.

Records genuine strategy/data eligibility rejections into SQLite.
This module never places orders and never changes trading decisions.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/perez_ai_memory.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT,
            signal TEXT,
            score REAL,
            options_score REAL,
            regime TEXT,
            reason TEXT NOT NULL,
            features_json TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def record_rejection(
    *,
    symbol: str = "",
    signal: str = "",
    score: float | None = None,
    options_score: float | None = None,
    regime: str = "",
    reason: str,
    features: dict[str, Any] | None = None,
    ts: str | None = None,
) -> bool:
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("REJECTION_REASON_REQUIRED")

    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO rejections
            (
                ts,
                symbol,
                signal,
                score,
                options_score,
                regime,
                reason,
                features_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts or datetime.now(timezone.utc).isoformat(),
                str(symbol or ""),
                str(signal or ""),
                float(score) if score is not None else None,
                float(options_score) if options_score is not None else None,
                str(regime or ""),
                reason,
                json.dumps(
                    features or {},
                    separators=(",", ":"),
                    default=str,
                ),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()
