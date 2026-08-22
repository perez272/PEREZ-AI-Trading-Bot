"""Persistent, auditable learning memory for PEREZ AI.

This is an adaptive statistical memory, not an autonomous code/strategy editor.
It records observations and outcomes in SQLite so knowledge survives restarts.
Safety/risk gates remain outside this module and cannot be bypassed by learning.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/memory/perez_ai_memory.db")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT,
            signal TEXT,
            score REAL,
            options_score REAL,
            regime TEXT,
            features_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT,
            signal TEXT,
            contract TEXT,
            score REAL,
            regime TEXT,
            pnl REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            exit_reason TEXT,
            features_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            category TEXT NOT NULL,
            lesson TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        );
        """
    )
    return conn


def remember_observation(candidate, options_result=None, regime="unknown"):
    options_result = options_result or {}
    features = {
        "trend": candidate.get("trend"),
        "volume_ratio": candidate.get("volume_ratio"),
        "close": candidate.get("close"),
        "options_score": options_result.get("options_score", 0),
    }
    with _connect() as conn:
        conn.execute(
            "INSERT INTO observations VALUES (NULL,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), candidate.get("symbol"),
             candidate.get("signal"), float(candidate.get("score", 0)),
             float(options_result.get("options_score", 0)), regime,
             json.dumps(features, default=str)),
        )


def remember_outcome(trade, result, regime="unknown"):
    pnl = float(result.get("pnl", 0))
    pnl_pct = float(result.get("pnl_percent", 0))
    features = {
        "expiry": trade.get("expiry"),
        "strike": trade.get("strike"),
        "entry": trade.get("entry"),
        "quantity": trade.get("quantity"),
        "investment": trade.get("investment"),
    }
    with _connect() as conn:
        conn.execute(
            "INSERT INTO outcomes VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), trade.get("symbol"),
             trade.get("signal"), trade.get("contract"),
             float(trade.get("score", 0)), regime, pnl, pnl_pct,
             result.get("exit_reason", "UNKNOWN"), json.dumps(features, default=str)),
        )


def _stats(conn, where="", params=()):
    row = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),0) wins, "
        f"COALESCE(SUM(pnl),0) pnl, COALESCE(AVG(pnl_percent),0) avg_pct FROM outcomes {where}",
        params,
    ).fetchone()
    return dict(row)


def learning_summary(symbol=None):
    with _connect() as conn:
        overall = _stats(conn)
        scoped = _stats(conn, "WHERE symbol = ?", (symbol,)) if symbol else None
        recent = conn.execute(
            "SELECT symbol, signal, pnl, pnl_percent, exit_reason, ts FROM outcomes ORDER BY id DESC LIMIT 8"
        ).fetchall()
    return {
        "overall": overall,
        "symbol": scoped,
        "recent": [dict(r) for r in recent],
    }


def ai_suggestion(symbol=None, score=0, signal=""):
    summary = learning_summary(symbol)
    s = summary["symbol"] or summary["overall"]
    n = int(s["n"])
    if n < 5:
        return "Learning: collecting evidence (need 5+ completed paper trades before adapting confidence)."
    win_rate = s["wins"] / n * 100
    if win_rate < 40:
        return f"AI suggestion: {symbol or 'this setup'} has weak recent evidence ({win_rate:.0f}% wins). Prefer waiting for stronger confirmation."
    if win_rate >= 60 and float(s["avg_pct"]) > 0:
        return f"AI suggestion: {symbol or 'this setup'} has positive learned evidence ({win_rate:.0f}% wins). Keep risk gates strict and favor confirmed signals."
    return f"AI suggestion: evidence is mixed ({win_rate:.0f}% wins). Do not increase risk; wait for confirmation."


def memory_status():
    summary = learning_summary()
    n = int(summary["overall"]["n"])
    return f"Memory: {n} completed paper trades stored | persistent SQLite learning"
