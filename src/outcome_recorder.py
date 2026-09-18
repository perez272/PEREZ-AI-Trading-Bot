"""Canonical closed-trade outcome persistence.

Records the active paper-trade lifecycle into the existing SQLite
``outcomes`` table. This module never places orders and never changes risk/trading decisions.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/perez_ai_memory.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
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
            features_json TEXT NOT NULL,
            trade_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            category TEXT NOT NULL,
            lesson TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_outcomes_trade_id
        ON outcomes(trade_id)
        WHERE trade_id IS NOT NULL AND trade_id != ''
    """)
    conn.commit()
    return conn


def record_closed_outcome(trade: dict[str, Any], result: dict[str, Any]) -> bool:
    trade_id = str(trade.get("trade_id") or "").strip()
    if not trade_id:
        raise ValueError("Cannot persist outcome without trade_id")
    if not result or not result.get("closed"):
        raise ValueError("OUTCOME_NOT_CLOSED")

    def num(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # Preserve the exact SURGE event that produced this trade so canonical
    # P&L outcomes can be learned against the original signal pattern.
    candidate = trade.get("learning_candidate")
    if not isinstance(candidate, dict):
        candidate = {}
    features = {
        "event_key": candidate.get("event_key") or trade.get("event_key"),
        "surge_score": trade.get("surge_score", candidate.get("score")),
        "surge_reasons": trade.get("surge_reasons", candidate.get("reasons")),
        "surge_move_1m_pct": trade.get("surge_move_1m_pct", candidate.get("move_1m_pct")),
        "surge_move_3m_pct": trade.get("surge_move_3m_pct", candidate.get("move_3m_pct")),
        "surge_move_5m_pct": trade.get("surge_move_5m_pct", candidate.get("move_5m_pct")),
        "surge_velocity": candidate.get("velocity"),
        "surge_acceleration": candidate.get("acceleration"),
        "surge_volume_ratio": candidate.get("volume_ratio"),
        "surge_spread_pct": candidate.get("spread_pct"),
        "surge_m15_trend": candidate.get("m15_trend"),
        "surge_h1_trend": candidate.get("h1_trend"),
        "surge_mtf_aligned": candidate.get("mtf_aligned"),
        "surge_underlying_direction": candidate.get("underlying_direction"),
        "surge_learning": trade.get("surge_learning"),
        "learning": trade.get("learning"),
        "underlying_score": trade.get("underlying_score"),
        "options_score": trade.get("options_score"),
        "momentum_score": trade.get("momentum_score"),
        "strategy": trade.get("strategy"),
        "momentum_strategy": trade.get("momentum_strategy"),
        "momentum_reasons": trade.get("momentum_reasons"),
        "fundamental_admitted": trade.get("fundamental_admitted"),
        "mtf_direction": trade.get("mtf_direction"),
        "expiry": trade.get("expiry"),
        "strike": trade.get("strike"),
        "option_live_ltp_at_gate": trade.get("option_live_ltp_at_gate"),
        "data_source": trade.get("data_source"),
        "entry": trade.get("entry"),
        "stop_loss": trade.get("stop_loss"),
        "target": trade.get("target"),
        "quantity": trade.get("original_quantity", trade.get("quantity")),
        "lots": trade.get("lots"),
        "investment": trade.get("investment"),
        "detected_at": trade.get("detected_at"),
        "opened_at": trade.get("opened_at"),
        "target1_at": trade.get("target1_at"),
        "closed_at": trade.get("closed_at") or result.get("closed_at"),
        "detection_to_open_seconds": result.get("detection_to_open_seconds"),
        "open_to_target1_seconds": result.get("open_to_target1_seconds"),
        "open_to_close_seconds": result.get("open_to_close_seconds"),
        "detection_to_close_seconds": result.get("detection_to_close_seconds"),
    }
    features = {k: v for k, v in features.items() if v is not None and v != ""}

    symbol = str(trade.get("symbol") or "")
    signal = str(trade.get("signal") or "")
    contract = str(result.get("contract") or trade.get("contract") or "")
    score = num(trade.get("underlying_score", trade.get("surge_score", trade.get("score", 0.0))))
    regime = str(trade.get("regime") or "")
    pnl = num(result.get("pnl"))
    pnl_percent = num(result.get("pnl_percent"))
    exit_reason = str(result.get("exit_reason") or "")

    exit_price = num(result.get("exit_price", result.get("current")))
    entry_price = num(trade.get("entry"))
    remaining_qty = num(result.get("remaining_quantity", result.get("quantity")))
    realized_pnl = num(result.get("realized_pnl", trade.get("realized_pnl")))
    calculated_pnl = round(realized_pnl + ((exit_price - entry_price) * remaining_qty), 2) if entry_price > 0 and exit_price > 0 else None
    features["exit_price"] = exit_price
    features["calculated_pnl"] = calculated_pnl
    features["pnl_delta"] = round(pnl - calculated_pnl, 2) if calculated_pnl is not None else None
    features["pnl_integrity_checked"] = calculated_pnl is not None

    closed_ts = str(trade.get("closed_at") or result.get("closed_at") or result.get("time") or "")
    conn = _connect()
    try:
        before = conn.total_changes
        conn.execute("""
            INSERT OR IGNORE INTO outcomes
            (ts,symbol,signal,contract,score,regime,pnl,pnl_percent,exit_reason,features_json,trade_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            closed_ts, symbol, signal, contract, score, regime, pnl, pnl_percent,
            exit_reason, json.dumps(features, separators=(",", ":"), default=str), trade_id,
        ))
        inserted = conn.total_changes > before
        if inserted:
            conn.execute(
                "INSERT INTO lessons(ts,category,lesson,evidence_json) VALUES(?,?,?,?)",
                (
                    closed_ts,
                    "TRADE_OUTCOME",
                    "Completed paper trade outcome stored for adaptive confidence; no strategy code is auto-modified.",
                    json.dumps({"trade": trade, "result": result}, separators=(",", ":"), default=str),
                ),
            )
        conn.commit()
        return inserted
    finally:
        conn.close()
