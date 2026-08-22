"""Options momentum/surge detector for PEREZ AI.

Detects +5%, +10% and +15% option-premium moves over 5/10/15 minute
observation windows. It is an event detector, not an automatic BUY signal.
Every event keeps option, underlying, regime, expiry context and available
indicator evidence for continuation/reversal learning.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path("data/memory/perez_ai_memory.db")
WINDOWS = (5, 10, 15)
THRESHOLDS = (5.0, 10.0, 15.0)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS option_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            epoch REAL NOT NULL,
            contract TEXT NOT NULL,
            symbol TEXT,
            option_type TEXT,
            expiry TEXT,
            strike REAL,
            ltp REAL NOT NULL,
            features_json TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS option_surge_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            contract TEXT NOT NULL,
            symbol TEXT,
            option_type TEXT,
            expiry TEXT,
            strike REAL,
            window_minutes INTEGER NOT NULL,
            threshold_pct REAL NOT NULL,
            change_pct REAL NOT NULL,
            start_ltp REAL NOT NULL,
            end_ltp REAL NOT NULL,
            expiry_bucket TEXT,
            features_json TEXT NOT NULL
        )"""
    )
    return conn


def _epoch(ts: Optional[str] = None) -> float:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return datetime.now(timezone.utc).timestamp()


def _expiry_bucket(expiry: Any) -> str:
    """Classify expiry without requiring the learning module (avoids import cycles)."""
    if not expiry:
        return "UNKNOWN"
    text = str(expiry).strip()
    parsed = None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return "UNKNOWN"
    days = (parsed - datetime.now().date()).days
    if days == 0:
        return "EXPIRY_DAY"
    if days == 1:
        return "EXPIRY_MINUS_1"
    if days == 2:
        return "EXPIRY_MINUS_2"
    if days > 2:
        return "NORMAL"
    return "POST_EXPIRY"


def _features(candidate: Dict[str, Any], option: Dict[str, Any], regime: str) -> Dict[str, Any]:
    """Capture available evidence without inventing unavailable Greeks/IV."""
    keys = (
        "close", "open", "high", "low", "RSI", "rsi", "EMA20", "EMA50", "EMA200",
        "MACD", "VWAP", "ATR", "ADX", "volume_ratio", "trend", "score",
        "breakout_score", "momentum_score", "mean_reversion_score", "volatility_score",
        "spread_pct", "slippage_pct", "volume", "open_interest", "oi_volume_ratio",
        "buy_quantity", "sell_quantity", "avg_price", "percent_change", "best_bid",
        "best_ask", "iv", "delta", "gamma", "theta", "vega",
    )
    out = {"regime": regime}
    for source in (candidate, option):
        for key in keys:
            if key in source and source[key] is not None:
                out[key] = source[key]
    out["live_market_data"] = bool(option.get("live_market_data"))
    out["iv_available"] = bool(option.get("iv_available"))
    out["greeks_available"] = bool(option.get("greeks_available"))
    return out


def _contract(option: Dict[str, Any]) -> str:
    return str(option.get("contract") or option.get("symbol") or "").strip()


def _previous(conn, contract: str, target_epoch: float):
    return conn.execute(
        "SELECT * FROM option_snapshots WHERE contract=? AND epoch<=? "
        "ORDER BY epoch DESC LIMIT 1",
        (contract, target_epoch + 45),
    ).fetchone()


def observe_option(candidate: Dict[str, Any], option: Dict[str, Any], regime: str = "unknown") -> list[Dict[str, Any]]:
    """Persist a live snapshot and return newly detected surge events."""
    contract = _contract(option)
    ltp = _num(option.get("ltp"))
    if not contract or ltp <= 0 or not option.get("live_market_data"):
        return []

    now_ts = _now()
    now_epoch = _epoch(now_ts)
    expiry = str(option.get("expiry") or "")
    option_type = str(option.get("option_type") or "")
    strike = _num(option.get("strike"), 0.0)
    expiry_class = _expiry_bucket(expiry)
    features = _features(candidate, option, regime)
    features["expiry_bucket"] = expiry_class
    events = []

    with _connect() as conn:
        for window in WINDOWS:
            previous = _previous(conn, contract, now_epoch - window * 60)
            if not previous or _num(previous["ltp"]) <= 0:
                continue
            start_ltp = _num(previous["ltp"])
            change_pct = (ltp - start_ltp) / start_ltp * 100.0
            for threshold in THRESHOLDS:
                if change_pct < threshold:
                    continue
                duplicate = conn.execute(
                    "SELECT 1 FROM option_surge_events WHERE contract=? AND "
                    "window_minutes=? AND threshold_pct=? AND ts>=? LIMIT 1",
                    (contract, window, threshold,
                     datetime.fromtimestamp(now_epoch - window * 60, timezone.utc).isoformat()),
                ).fetchone()
                if duplicate:
                    continue
                event = {
                    "timestamp": now_ts,
                    "contract": contract,
                    "symbol": option.get("symbol") or candidate.get("symbol"),
                    "option_type": option_type,
                    "expiry": expiry,
                    "strike": strike,
                    "window_minutes": window,
                    "threshold_pct": threshold,
                    "change_pct": round(change_pct, 2),
                    "start_ltp": start_ltp,
                    "end_ltp": ltp,
                    "expiry_bucket": expiry_class,
                    "features": features,
                }
                conn.execute(
                    "INSERT INTO option_surge_events VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now_ts, contract, event["symbol"], option_type, expiry, strike,
                     window, threshold, change_pct, start_ltp, ltp,
                     expiry_class, json.dumps(features, default=str)),
                )
                events.append(event)

        conn.execute(
            "INSERT INTO option_snapshots(ts,epoch,contract,symbol,option_type,expiry,strike,ltp,features_json) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (now_ts, now_epoch, contract, option.get("symbol") or candidate.get("symbol"),
             option_type, expiry, strike, ltp, json.dumps(features, default=str)),
        )
        conn.execute(
            "DELETE FROM option_snapshots WHERE id NOT IN "
            "(SELECT id FROM option_snapshots ORDER BY id DESC LIMIT 5000)"
        )
    return events


def surge_summary(limit: int = 10) -> list[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts,contract,symbol,option_type,expiry,strike,window_minutes,threshold_pct,change_pct,start_ltp,end_ltp,expiry_bucket "
            "FROM option_surge_events ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(row) for row in rows]
