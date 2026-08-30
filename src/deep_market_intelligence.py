"""Deep market intelligence over already-acquired validated market snapshots.

This module deliberately performs ZERO broker/market-data API calls. It consumes
normalized scanner snapshots and feeds compact evidence into the existing
learning_status persistence layer. It is observational/paper-only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_PATH = Path(os.getenv("DEEP_MARKET_MEMORY", "data/memory/deep_market_intelligence.sqlite3"))
WINDOW_SECONDS = float(os.getenv("DEEP_MARKET_WINDOW_SECONDS", "300"))
MAX_SNAPSHOTS = int(os.getenv("DEEP_MARKET_MAX_SNAPSHOTS", "3000"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DeepMarketIntelligence:
    """Analyze scanner output without acquiring any additional market data."""

    def __init__(self, db_path: Path = MEMORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                observed_ts TEXT NOT NULL,
                source TEXT,
                score REAL,
                close REAL,
                rsi REAL,
                percent_change REAL,
                breakout_strength REAL,
                body_strength REAL,
                atr_pct REAL,
                volume_ratio REAL,
                signal TEXT,
                trend TEXT,
                m15_trend TEXT,
                h1_trend TEXT,
                expiry_context TEXT,
                deep_score REAL,
                regime TEXT,
                reasons_json TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_deep_symbol_ts ON snapshots(symbol, observed_ts)")

    @staticmethod
    def _expiry_context(snapshot: dict[str, Any]) -> str:
        """Use expiry metadata when supplied; never infer a date from market data."""
        value = snapshot.get("expiry_context") or snapshot.get("expiry") or "UNKNOWN"
        return str(value)

    def _analyze(self, snapshot: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
        score = max(0.0, min(100.0, _f(snapshot.get("score"))))
        momentum = _f(snapshot.get("percent_change"))
        breakout = _f(snapshot.get("breakout_strength"))
        body = _f(snapshot.get("body_strength"))
        volume = _f(snapshot.get("volume_ratio"), 1.0)
        rsi = _f(snapshot.get("rsi"))
        atr_pct = _f(snapshot.get("atr_pct"))
        acceleration = 0.0
        if previous is not None:
            acceleration = momentum - _f(previous.get("percent_change"))

        deep_score = score
        reasons: list[str] = []
        if abs(momentum) >= 0.5:
            deep_score += min(10.0, abs(momentum) * 4.0)
            reasons.append("momentum_expansion")
        if abs(acceleration) >= 0.25:
            deep_score += min(10.0, abs(acceleration) * 8.0)
            reasons.append("acceleration")
        if breakout > 0:
            deep_score += min(8.0, breakout * 2.0)
            reasons.append("breakout_pressure")
        if volume >= 1.5:
            deep_score += min(8.0, (volume - 1.0) * 5.0)
            reasons.append("volume_expansion")
        if body >= 0.7:
            deep_score += 4.0
            reasons.append("strong_candle_body")
        if atr_pct >= 0.5:
            deep_score += 3.0
            reasons.append("volatility_expansion")
        if rsi >= 70 or (0 < rsi <= 30):
            reasons.append("momentum_extreme")

        deep_score = round(max(0.0, min(100.0, deep_score)), 2)
        if deep_score >= 80:
            regime = "HIGH_MOVE"
        elif deep_score >= 65:
            regime = "ACTIVE"
        elif deep_score >= 45:
            regime = "NEUTRAL"
        else:
            regime = "QUIET"

        return {
            "deep_score": deep_score,
            "regime": regime,
            "acceleration": round(acceleration, 4),
            "reasons": reasons,
            "expiry_context": self._expiry_context(snapshot),
        }

    def process(self, snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...], observed_ts: str | None = None) -> list[dict[str, Any]]:
        """Process already-acquired snapshots. Never calls a broker/API."""
        observed_ts = observed_ts or _now_iso()
        results: list[dict[str, Any]] = []
        now = time.monotonic()
        with self._connect() as db:
            for snapshot in snapshots or []:
                if not isinstance(snapshot, dict) or not snapshot.get("symbol"):
                    continue
                symbol = str(snapshot["symbol"]).upper().strip()
                history = self._history.setdefault(symbol, deque(maxlen=20))
                previous = history[-1] if history else None
                analysis = self._analyze(snapshot, previous)
                enriched = {**snapshot, **analysis, "observed_ts": observed_ts, "engine": "shared_snapshot"}
                results.append(enriched)
                history.append(dict(snapshot))
                db.execute(
                    """INSERT INTO snapshots(
                    symbol,observed_ts,source,score,close,rsi,percent_change,
                    breakout_strength,body_strength,atr_pct,volume_ratio,signal,
                    trend,m15_trend,h1_trend,expiry_context,deep_score,regime,reasons_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (symbol, observed_ts, snapshot.get("data_source"), _f(snapshot.get("score")),
                     _f(snapshot.get("close")), _f(snapshot.get("rsi")), _f(snapshot.get("percent_change")),
                     _f(snapshot.get("breakout_strength")), _f(snapshot.get("body_strength")),
                     _f(snapshot.get("atr_pct")), _f(snapshot.get("volume_ratio")), snapshot.get("signal"),
                     snapshot.get("trend"), snapshot.get("m15_trend"), snapshot.get("h1_trend"),
                     analysis["expiry_context"], analysis["deep_score"], analysis["regime"],
                     json.dumps(analysis["reasons"], separators=(",", ":"))),
                )
            db.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)", (MAX_SNAPSHOTS,))
        _ = now  # keeps the processing contract explicit: local timing only.
        return results

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            high = int(db.execute("SELECT COUNT(*) FROM snapshots WHERE regime='HIGH_MOVE'").fetchone()[0])
            latest = db.execute("SELECT observed_ts FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return {"snapshots": total, "high_move_states": high, "last_observed": latest[0] if latest else None}


_engine = DeepMarketIntelligence()


def process_market_snapshots(snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...], observed_ts: str | None = None) -> list[dict[str, Any]]:
    return _engine.process(snapshots, observed_ts)


def get_deep_market_intelligence() -> DeepMarketIntelligence:
    return _engine
