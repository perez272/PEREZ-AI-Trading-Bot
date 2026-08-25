"""Persistent, auditable learning memory for PEREZ AI.

Adaptive statistical memory only: it never edits strategy code and cannot
bypass risk/execution gates. Rejected candidates are remembered too, so the
system learns when *not* to trade. Completed paper-trade outcomes are keyed by
trade_id so one closed trade can never be learned twice.
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
            trade_id TEXT,
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
    # Safe migration for databases created before trade_id existed.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(outcomes)")}
    if "trade_id" not in columns:
        conn.execute("ALTER TABLE outcomes ADD COLUMN trade_id TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_outcomes_trade_id ON outcomes(trade_id) WHERE trade_id IS NOT NULL")
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rich_features(candidate, options_result):
    """Capture all available evidence without fabricating unavailable fields."""
    features = {}
    keys = (
        "close", "open", "high", "low", "volume", "volume_ratio", "trend",
        "score", "breakout_score", "momentum_score", "mean_reversion_score",
        "RSI", "rsi", "EMA20", "EMA50", "EMA200", "MACD", "VWAP", "ATR", "ADX",
        "volatility_score", "vwap_score", "regime", "structure",
    )
    for source in (candidate or {}, options_result or {}):
        for key in keys:
            if key in source and source[key] is not None:
                features[key] = source[key]
    option_keys = (
        "contract", "option_type", "expiry", "strike", "ltp", "volume",
        "open_interest", "oi_volume_ratio", "buy_quantity", "sell_quantity",
        "last_trade_qty", "avg_price", "net_change", "percent_change",
        "best_bid", "best_ask", "spread_pct", "slippage_pct", "iv", "delta",
        "gamma", "theta", "vega", "iv_available", "greeks_available",
        "oi_change_available", "live_market_data", "live_data_error",
    )
    for key in option_keys:
        if key in (options_result or {}) and options_result[key] is not None:
            features[key] = options_result[key]
    return features


def remember_observation(candidate, options_result=None, regime="unknown"):
    options_result = options_result or {}
    features = _rich_features(candidate, options_result)
    features["expiry"] = options_result.get("expiry", features.get("expiry"))
    surge_events = []
    try:
        from src.options_surge_engine import observe_option
        from src.expiry_learning_engine import learn_from_surge
        surge_events = observe_option(candidate, options_result, regime=regime)
        for event in surge_events:
            event["expiry_learning"] = learn_from_surge(event)
        if surge_events:
            options_result["surge_events"] = surge_events
            options_result["expiry_learning"] = surge_events[-1].get("expiry_learning")
    except Exception as exc:
        features["surge_engine_error"] = repr(exc)

    with _connect() as conn:
        conn.execute(
            "INSERT INTO observations (ts,symbol,signal,score,options_score,regime,features_json) VALUES (?,?,?,?,?,?,?)",
            (_now(), candidate.get("symbol"), candidate.get("signal"),
             float(candidate.get("score", 0)), float(options_result.get("options_score", 0)),
             regime, json.dumps(features, default=str)),
        )
        if surge_events:
            conn.execute(
                "INSERT INTO lessons(ts,category,lesson,evidence_json) VALUES(?,?,?,?)",
                (_now(), "OPTIONS_SURGE", "Detected option premium surge; retain event and expiry context for later outcome learning.",
                 json.dumps(surge_events, default=str)),
            )


def remember_rejection(candidate, reason, options_result=None, regime="unknown"):
    options_result = options_result or {}
    features = _rich_features(candidate, options_result)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO rejections VALUES (NULL,?,?,?,?,?,?,?)",
            (_now(), candidate.get("symbol"), candidate.get("signal"),
             float(candidate.get("score", 0)), float(options_result.get("options_score", 0)),
             regime, str(reason), json.dumps(features, default=str)),
        )


def remember_outcome(trade, result, regime="unknown"):
    """Store exactly one completed paper-trade outcome.

    A missing trade_id is rejected rather than silently creating an
    uncorrelatable learning record. Duplicate delivery is treated as a
    successful idempotent no-op.
    """
    trade_id = str(trade.get("trade_id") or "").strip()
    if not trade_id:
        raise ValueError("CLOSED_PAPER_TRADE_MISSING_TRADE_ID")
    if not result or not result.get("closed"):
        raise ValueError("OUTCOME_NOT_CLOSED")

    pnl = float(result.get("pnl", 0))
    pnl_pct = float(result.get("pnl_percent", 0))
    features = {
        "trade_id": trade_id,
        "expiry": trade.get("expiry"), "strike": trade.get("strike"),
        "entry": trade.get("entry"), "quantity": trade.get("quantity"),
        "investment": trade.get("investment"), "ensemble_score": trade.get("ensemble_score"),
        "options_score": trade.get("options_score"), "ai_confidence": trade.get("ai_confidence"),
        "market_data_source": trade.get("data_source"),
        "exit": result.get("current"),
    }
    with _connect() as conn:
        existing = conn.execute("SELECT id FROM outcomes WHERE trade_id = ?", (trade_id,)).fetchone()
        if existing:
            return {"stored": False, "duplicate": True, "trade_id": trade_id, "outcome_id": int(existing["id"])}
        cursor = conn.execute(
            """INSERT INTO outcomes
               (ts,trade_id,symbol,signal,contract,score,regime,pnl,pnl_percent,exit_reason,features_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), trade_id, trade.get("symbol"), trade.get("signal"), trade.get("contract"),
             float(trade.get("score", 0)), regime, pnl, pnl_pct,
             result.get("exit_reason", "UNKNOWN"), json.dumps(features, default=str)),
        )
        conn.execute(
            "INSERT INTO lessons(ts,category,lesson,evidence_json) VALUES(?,?,?,?)",
            (_now(), "TRADE_OUTCOME",
             "Completed paper trade outcome stored for adaptive confidence; no strategy code is auto-modified.",
             json.dumps({"trade": trade, "result": result}, default=str)),
        )
        return {"stored": True, "duplicate": False, "trade_id": trade_id, "outcome_id": int(cursor.lastrowid)}


def _stats(conn, where="", params=()):
    row = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),0) wins, "
        f"COALESCE(SUM(pnl),0) pnl, COALESCE(AVG(pnl_percent),0) avg_pct FROM outcomes {where}", params
    ).fetchone()
    return dict(row)


def learning_summary(symbol=None, regime=None):
    with _connect() as conn:
        clauses, params = [], []
        if symbol:
            clauses.append("symbol = ?"); params.append(symbol)
        if regime:
            clauses.append("regime = ?"); params.append(regime)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        scoped = _stats(conn, where, tuple(params))
        overall = _stats(conn)
        counts = {
            "observations": int(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]),
            "rejections": int(conn.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]),
            "lessons": int(conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]),
        }
        recent = conn.execute("SELECT trade_id, symbol, signal, pnl, pnl_percent, exit_reason, regime, ts FROM outcomes ORDER BY id DESC LIMIT 8").fetchall()
    return {"overall": overall, "scope": scoped, "counts": counts, "recent": [dict(r) for r in recent]}


def learned_confidence(symbol=None, regime=None):
    stats = learning_summary(symbol, regime)["scope"]
    n = int(stats["n"])
    if n == 0:
        return 50.0
    win_rate = stats["wins"] / n * 100
    edge_bonus = max(-20.0, min(20.0, float(stats["avg_pct"]) * 4.0))
    sample_weight = min(1.0, n / 30.0)
    return round(50.0 + ((win_rate - 50.0) * sample_weight) + edge_bonus * sample_weight, 2)


def ai_suggestion(symbol=None, score=0, signal="", regime=None):
    summary = learning_summary(symbol, regime)
    s = summary["scope"]
    n = int(s["n"])
    if n < 5:
        return "Collecting evidence — keep confidence neutral until at least 5 completed paper trades exist."
    win_rate = s["wins"] / n * 100
    if win_rate < 40:
        return f"Weak learned evidence ({win_rate:.0f}% wins). Prefer waiting for stronger confirmation."
    if win_rate >= 60 and float(s["avg_pct"]) > 0:
        return f"Positive learned evidence ({win_rate:.0f}% wins). Favor confirmed setups; keep risk gates strict."
    return f"Mixed evidence ({win_rate:.0f}% wins). Do not increase risk; wait for confirmation."


def memory_status():
    summary = learning_summary()
    n = int(summary["overall"]["n"])
    counts = summary["counts"]
    try:
        from src.options_surge_engine import surge_summary
        surge_count = len(surge_summary(500))
    except Exception:
        surge_count = 0
    return {
        "completed_trades": n,
        "wins": int(summary["overall"]["wins"]),
        "win_rate_pct": round((summary["overall"]["wins"] / n * 100) if n else 0.0, 2),
        "pnl": round(float(summary["overall"]["pnl"]), 2),
        "observations": counts["observations"],
        "rejections": counts["rejections"],
        "lessons": counts["lessons"],
        "surge_events": surge_count,
        "outcome_learning": "ACTIVE" if n else "WAITING_FOR_FIRST_CLOSED_TRADE",
        "pattern_learning": "ACTIVE" if counts["observations"] else "WAITING_FOR_OBSERVATIONS",
    }
