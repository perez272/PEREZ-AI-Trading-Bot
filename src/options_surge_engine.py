"""Options momentum/surge detector and rich precursor recorder for PEREZ AI.

Observational/paper-only. Every valid live option observation is persisted so
research can study the conditions before 8x/20x/50x/100x premium expansions.
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
MAX_SNAPSHOTS = 50000


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_snapshots_contract_epoch ON option_snapshots(contract, epoch)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_surge_contract_ts ON option_surge_events(contract, ts)")
    return conn


def _epoch(ts: Optional[str] = None) -> float:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return datetime.now(timezone.utc).timestamp()


def _expiry_bucket(expiry: Any) -> str:
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


def _features(candidate: Dict[str, Any], option: Dict[str, Any], regime: str, previous: Optional[sqlite3.Row]) -> Dict[str, Any]:
    keys = (
        "close", "open", "high", "low", "previous_close", "RSI", "rsi", "rsi_slope",
        "EMA20", "EMA50", "EMA200", "MACD", "VWAP", "ATR", "ADX", "volume_ratio",
        "trend", "score", "breakout_score", "breakout_strength", "momentum_score",
        "mean_reversion_score", "volatility_score", "structure", "spread_pct", "slippage_pct",
        "volume", "open_interest", "oi", "oi_change", "oi_change_pct", "oi_volume_ratio",
        "buy_quantity", "sell_quantity", "last_trade_qty", "avg_price", "percent_change",
        "best_bid", "best_ask", "bid", "ask", "iv", "delta", "gamma", "theta", "vega", "rho",
        "spot_ltp", "futures_ltp", "distance_to_spot", "distance_to_spot_pct", "atm_distance",
        "ce_volume", "pe_volume", "ce_oi", "pe_oi", "ce_pe_volume_ratio", "ce_pe_oi_ratio",
        "minutes_to_expiry", "expiry_bucket",
    )
    out: Dict[str, Any] = {"regime": regime}
    market_data = option.get("market_data") if isinstance(option.get("market_data"), dict) else {}
    for source in (candidate, option, market_data):
        for key in keys:
            if key in source and source[key] is not None:
                out[key] = source[key]
    out["live_market_data"] = bool(option.get("live_market_data"))
    out["iv_available"] = bool(option.get("iv_available", out.get("iv") is not None))
    out["greeks_available"] = bool(option.get("greeks_available", any(out.get(k) is not None for k in ("delta", "gamma", "theta", "vega"))))

    if previous:
        try:
            previous_features = json.loads(previous["features_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            previous_features = {}
        prev_ltp = _optional_num(previous["ltp"])
        now_ltp = _optional_num(out.get("ltp"))
        if prev_ltp and now_ltp:
            out["premium_change_pct_since_previous"] = (now_ltp - prev_ltp) / prev_ltp * 100.0
        prev_volume = _optional_num(previous_features.get("volume"))
        now_volume = _optional_num(out.get("volume"))
        if prev_volume and now_volume and prev_volume > 0:
            out["volume_ratio_since_previous"] = now_volume / prev_volume
            out["volume_change_pct"] = (now_volume - prev_volume) / prev_volume * 100.0
        for key in ("open_interest", "iv", "delta", "gamma", "theta", "vega", "spot_ltp", "futures_ltp"):
            old = _optional_num(previous_features.get(key))
            new = _optional_num(out.get(key))
            if old is not None and new is not None:
                out[f"{key}_change"] = new - old
                if old != 0:
                    out[f"{key}_change_pct"] = (new - old) / abs(old) * 100.0
    return out


def _contract(option: Dict[str, Any], candidate: Optional[Dict[str, Any]] = None) -> str:
    candidate = candidate or {}
    return str(
        option.get("contract") or option.get("trading_symbol") or
        candidate.get("contract") or option.get("symbol") or candidate.get("symbol") or ""
    ).strip()


def _previous(conn, contract: str, target_epoch: float):
    return conn.execute(
        "SELECT * FROM option_snapshots WHERE contract=? AND epoch<=? ORDER BY epoch DESC LIMIT 1",
        (contract, target_epoch + 45),
    ).fetchone()


def observe_option(candidate: Dict[str, Any], option: Dict[str, Any], regime: str = "unknown") -> list[Dict[str, Any]]:
    """Persist every valid live snapshot and return newly detected surge events."""
    market_data = option.get("market_data") if isinstance(option.get("market_data"), dict) else {}
    contract = _contract(option, candidate)
    ltp = _num(option.get("ltp", market_data.get("ltp", candidate.get("ltp"))))
    if not contract or ltp <= 0 or not option.get("live_market_data"):
        return []

    now_ts = _now()
    now_epoch = _epoch(now_ts)
    expiry = str(option.get("expiry") or candidate.get("expiry") or market_data.get("expiry") or "")
    option_type = str(option.get("option_type") or candidate.get("option_type") or "")
    strike = _num(option.get("strike", candidate.get("strike", market_data.get("strike"))), 0.0)
    expiry_class = _expiry_bucket(expiry)
    with _connect() as conn:
        previous = _previous(conn, contract, now_epoch - 90)
        features = _features(candidate, option, regime, previous)
        features["expiry_bucket"] = expiry_class
        events = []

        for window in WINDOWS:
            previous_window = _previous(conn, contract, now_epoch - window * 60)
            if not previous_window or _num(previous_window["ltp"]) <= 0:
                continue
            start_ltp = _num(previous_window["ltp"])
            change_pct = (ltp - start_ltp) / start_ltp * 100.0
            for threshold in THRESHOLDS:
                if change_pct < threshold:
                    continue
                duplicate = conn.execute(
                    "SELECT 1 FROM option_surge_events WHERE contract=? AND window_minutes=? AND threshold_pct=? AND ts>=? LIMIT 1",
                    (contract, window, threshold, datetime.fromtimestamp(now_epoch - window * 60, timezone.utc).isoformat()),
                ).fetchone()
                if duplicate:
                    continue
                event = {
                    "timestamp": now_ts, "contract": contract,
                    "symbol": option.get("symbol") or candidate.get("symbol"),
                    "option_type": option_type, "expiry": expiry, "strike": strike,
                    "window_minutes": window, "threshold_pct": threshold,
                    "change_pct": round(change_pct, 2), "start_ltp": start_ltp,
                    "end_ltp": ltp, "expiry_bucket": expiry_class, "features": features,
                }
                conn.execute(
                    "INSERT INTO option_surge_events(ts,contract,symbol,option_type,expiry,strike,window_minutes,threshold_pct,change_pct,start_ltp,end_ltp,expiry_bucket,features_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now_ts, contract, event["symbol"], option_type, expiry, strike,
                     window, threshold, change_pct, start_ltp, ltp,
                     expiry_class, json.dumps(features, default=str)),
                )
                events.append(event)

        conn.execute(
            "INSERT INTO option_snapshots(ts,epoch,contract,symbol,option_type,expiry,strike,ltp,features_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (now_ts, now_epoch, contract, option.get("symbol") or candidate.get("symbol"),
             option_type, expiry, strike, ltp, json.dumps(features, default=str)),
        )
        conn.execute(
            "DELETE FROM option_snapshots WHERE id NOT IN (SELECT id FROM option_snapshots ORDER BY id DESC LIMIT ?)",
            (MAX_SNAPSHOTS,),
        )
    return events


def surge_summary(limit: int = 10) -> list[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts,contract,symbol,option_type,expiry,strike,window_minutes,threshold_pct,change_pct,start_ltp,end_ltp,expiry_bucket FROM option_surge_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]
