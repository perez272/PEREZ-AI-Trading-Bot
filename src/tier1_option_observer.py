"""Continuous Tier-1 option-chain observer and persistent move learner.

Observational only: never places or forces a trade. Persists successful chain
observations and move events so Telegram can report genuine evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.alternative_market_data import get_upstox_client
from src.explosive_move_detector import ExplosiveMoveSignal, detect_explosive_move

TIER1_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
MOVE_THRESHOLDS = (5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
MEMORY_PATH = Path(os.getenv("TIER1_OPTION_MEMORY", "data/memory/tier1_option_moves.sqlite3"))
BASELINE_TTL_SECONDS = int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS", "900"))
# Observation stays on the 5-second engine cadence, while provider refreshes
# are independently TTL-gated. This prevents six Tier-1 REST requests every
# five seconds while still feeding the detector every observation cycle.
CHAIN_REFRESH_TTL_SECONDS = int(os.getenv("TIER1_OPTION_CHAIN_REFRESH_TTL_SECONDS", "15"))
MAX_MEMORY_ROWS = int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS", "50000"))
HISTORY_POINTS = 30


class Tier1OptionObserver:
    def __init__(self, db_path: Path = MEMORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=HISTORY_POINTS))
        self._chain_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS baselines (
                contract_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, option_type TEXT,
                expiry TEXT, strike REAL, baseline_ltp REAL NOT NULL,
                baseline_ts TEXT NOT NULL, last_ltp REAL NOT NULL, last_ts TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS move_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL, option_type TEXT, contract TEXT, expiry TEXT,
                strike REAL, threshold REAL NOT NULL, baseline_ltp REAL NOT NULL,
                ltp REAL NOT NULL, move_pct REAL NOT NULL, observed_ts TEXT NOT NULL,
                features_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
                observed_ts TEXT NOT NULL, contracts_seen INTEGER NOT NULL,
                events_count INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_move_symbol_threshold ON move_events(symbol, threshold)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS early_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    instrument_key TEXT NOT NULL,
                    expiry TEXT,
                    strike REAL,
                    ltp REAL NOT NULL,
                    score REAL NOT NULL,
                    move_1m_pct REAL,
                    move_3m_pct REAL,
                    move_5m_pct REAL,
                    velocity REAL,
                    acceleration REAL,
                    volume_ratio REAL,
                    spread_pct REAL,
                    reasons_json TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    observed_ts TEXT NOT NULL,
                    detection_ts TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_early_events_pending ON early_events(consumed, observed_ts)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS observer_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
            """)
            existing_total = db.execute(
                "SELECT value FROM observer_meta WHERE key='surge_events_total'"
            ).fetchone()
            if existing_total is None:
                retained = db.execute(
                    "SELECT COUNT(*) FROM move_events"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO observer_meta(key,value) VALUES('surge_events_total',?)",
                    (int(retained),),
                )
            db.execute("CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations(observed_ts)")

    @staticmethod
    def _contract_key(symbol: str, row: dict[str, Any], option_type: str) -> str:
        raw = "|".join(str(x or "") for x in (symbol, option_type, row.get("instrument_key"), row.get("expiry"), row.get("strike_price")))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _market(row: dict[str, Any], option_type: str) -> dict[str, Any]:
        return row.get("call_options" if option_type == "CE" else "put_options") or {}

    def _features(self, symbol: str, option_type: str, row: dict[str, Any], market: dict[str, Any], move_pct: float, baseline: float) -> dict[str, Any]:
        md = market.get("market_data") or {}
        greeks = market.get("option_greeks") if isinstance(market.get("option_greeks"), dict) else {}
        return {
            "symbol": symbol, "option_type": option_type,
            "instrument_key": market.get("instrument_key"),
            "contract": market.get("trading_symbol") or row.get("trading_symbol"),
            "expiry": row.get("expiry"), "strike": row.get("strike_price"),
            "move_pct": round(move_pct, 4), "baseline_ltp": round(baseline, 4),
            "ltp": md.get("ltp"), "bid": md.get("bid_price"), "ask": md.get("ask_price"),
            "volume": md.get("volume"), "oi": md.get("oi"),
            "iv": greeks.get("iv"), "delta": greeks.get("delta"), "gamma": greeks.get("gamma"),
            "theta": greeks.get("theta"), "vega": greeks.get("vega"),
        }

    def _record_fast_signal(self, symbol: str, option_type: str, market: dict[str, Any], observed_ts: str) -> ExplosiveMoveSignal | None:
        key = str(market.get("instrument_key") or "")
        if not key:
            return None
        snapshot = dict(market)
        snapshot["observed_ts"] = observed_ts
        history = list(self._history[key])
        signal = detect_explosive_move(symbol, option_type, snapshot, history)
        self._history[key].append(snapshot)
        return signal

    def observe(self, symbol: str, chain: list[dict[str, Any]], observed_ts: str | None = None) -> list[dict[str, Any]]:
        if symbol not in TIER1_SYMBOLS:
            raise ValueError(f"Tier-1 observer rejected non-Tier-1 symbol: {symbol}")
        observed_ts = observed_ts or datetime.now(timezone.utc).isoformat()
        now_epoch = time.time()
        events: list[dict[str, Any]] = []
        valid_contracts = 0
        with self._connect() as db:
            for row in chain or []:
                for option_type in ("CE", "PE"):
                    market = self._market(row, option_type)
                    md = market.get("market_data") or {}
                    try:
                        ltp = float(md.get("ltp", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    if ltp <= 0 or not market.get("instrument_key"):
                        continue
                    valid_contracts += 1

                    fast = self._record_fast_signal(symbol, option_type, market, observed_ts)
                    if fast and fast.early:
                        features = self._features(
                            symbol, option_type, row, market,
                            fast.move_5m_pct, fast.ltp,
                        )
                        detection_ts = datetime.now(timezone.utc).isoformat()
                        early_key = f"{fast.instrument_key}|EARLY|{observed_ts[:19]}"
                        early_event = {
                            "type": "EARLY_EXPLOSIVE",
                            "symbol": symbol,
                            "option_type": option_type,
                            "score": fast.score,
                            "move_1m_pct": fast.move_1m_pct,
                            "move_3m_pct": fast.move_3m_pct,
                            "move_5m_pct": fast.move_5m_pct,
                            "velocity": fast.velocity_pct_per_min,
                            "acceleration": fast.acceleration_pct_per_min2,
                            "volume_ratio": fast.volume_ratio,
                            "spread_pct": fast.spread_pct,
                            "reasons": list(fast.reasons),
                            "instrument_key": fast.instrument_key,
                            "ltp": fast.ltp,
                            "expiry": row.get("expiry"),
                            "strike": row.get("strike_price"),
                            "contract": features.get("contract"),
                        }
                        try:
                            db.execute(
                                """INSERT INTO early_events(
                                    event_key,symbol,option_type,instrument_key,expiry,strike,
                                    ltp,score,move_1m_pct,move_3m_pct,move_5m_pct,
                                    velocity,acceleration,volume_ratio,spread_pct,
                                    reasons_json,features_json,observed_ts,detection_ts
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    early_key, symbol, option_type, fast.instrument_key,
                                    row.get("expiry"), row.get("strike_price"), fast.ltp,
                                    fast.score, fast.move_1m_pct, fast.move_3m_pct,
                                    fast.move_5m_pct, fast.velocity_pct_per_min,
                                    fast.acceleration_pct_per_min2, fast.volume_ratio,
                                    fast.spread_pct, json.dumps(list(fast.reasons)),
                                    json.dumps(features, separators=(",", ":")),
                                    observed_ts, detection_ts,
                                ),
                            )
                        except sqlite3.IntegrityError:
                            pass
                        events.append(early_event)

                    key = self._contract_key(symbol, row, option_type)
                    existing = db.execute("SELECT baseline_ltp, baseline_ts, last_ltp FROM baselines WHERE contract_key=?", (key,)).fetchone()
                    if not existing:
                        db.execute("INSERT INTO baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (key, symbol, option_type, row.get("expiry"), row.get("strike_price"), ltp, observed_ts, ltp, observed_ts))
                        continue
                    baseline, baseline_ts, _ = existing
                    try:
                        baseline_age = now_epoch - datetime.fromisoformat(baseline_ts).timestamp()
                    except (ValueError, TypeError):
                        baseline_age = BASELINE_TTL_SECONDS + 1
                    if baseline_age > BASELINE_TTL_SECONDS or ltp < baseline * 0.5:
                        db.execute("UPDATE baselines SET baseline_ltp=?, baseline_ts=?, last_ltp=?, last_ts=? WHERE contract_key=?", (ltp, observed_ts, ltp, observed_ts, key))
                        continue
                    move_pct = (ltp - baseline) / baseline * 100.0
                    for threshold in MOVE_THRESHOLDS:
                        if move_pct < threshold:
                            continue
                        event_key = f"{key}|{threshold}|{observed_ts[:16]}"
                        features = self._features(symbol, option_type, row, market, move_pct, baseline)
                        try:
                            detection_ts = datetime.now(timezone.utc).isoformat()
                            db.execute("INSERT INTO move_events(event_key,symbol,option_type,contract,expiry,strike,threshold,baseline_ltp,ltp,move_pct,observed_ts,detection_ts,features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (event_key, symbol, option_type, features.get("contract"), row.get("expiry"), row.get("strike_price"), threshold, baseline, ltp, move_pct, observed_ts, detection_ts, json.dumps(features, separators=(",", ":"))))
                            db.execute(
                                "UPDATE observer_meta SET value=value+1 "
                                "WHERE key='surge_events_total'"
                            )
                            events.append({"type": "THRESHOLD", "threshold": threshold, **features})
                        except sqlite3.IntegrityError:
                            pass
                    db.execute("UPDATE baselines SET last_ltp=?, last_ts=? WHERE contract_key=?", (ltp, observed_ts, key))
            if valid_contracts:
                db.execute("INSERT INTO observations(symbol,observed_ts,contracts_seen,events_count) VALUES (?,?,?,?)", (symbol, observed_ts, valid_contracts, len(events)))
            db.execute("DELETE FROM move_events WHERE id NOT IN (SELECT id FROM move_events ORDER BY id DESC LIMIT ?)", (MAX_MEMORY_ROWS,))
        return events

    def observe_all(self) -> list[dict[str, Any]]:
        client = get_upstox_client()
        if not client.available():
            return []
        events: list[dict[str, Any]] = []
        now = time.monotonic()
        for symbol in TIER1_SYMBOLS:
            try:
                cached = self._chain_cache.get(symbol)
                if cached and now - cached[0] < CHAIN_REFRESH_TTL_SECONDS:
                    chain = cached[1]
                    source = "cache"
                else:
                    chain = client.get_option_chain(symbol)
                    if chain:
                        self._chain_cache[symbol] = (time.monotonic(), chain)
                    source = "upstox"
                if chain and source == "upstox":
                    # Only a genuinely refreshed provider snapshot advances
                    # detector history. Cached snapshots must never receive a
                    # new wall-clock timestamp and masquerade as new market data.
                    observed_ts = datetime.now(timezone.utc).isoformat()
                    events.extend(self.observe(symbol, chain, observed_ts=observed_ts))
                    print(f"[TIER1 OBSERVER] {symbol}: observation source={source}")
                elif chain:
                    print(f"[TIER1 OBSERVER] {symbol}: cached snapshot — detector history unchanged")
            except Exception as exc:
                print(f"[TIER1 OBSERVER] {symbol}: {exc}")
        return events

    def get_pending_early_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id,event_key,symbol,option_type,instrument_key,expiry,strike,ltp,score,move_1m_pct,move_3m_pct,move_5m_pct,velocity,acceleration,volume_ratio,spread_pct,reasons_json,features_json,observed_ts,detection_ts FROM early_events WHERE consumed=0 ORDER BY observed_ts DESC,id DESC LIMIT ?", (max(1,int(limit)),)).fetchall()
        fields=("id","event_key","symbol","option_type","instrument_key","expiry","strike","ltp","score","move_1m_pct","move_3m_pct","move_5m_pct","velocity","acceleration","volume_ratio","spread_pct","reasons_json","features_json","observed_ts","detection_ts")
        out=[]
        for row in rows:
            e=dict(zip(fields,row))
            try: e["reasons"]=json.loads(e.pop("reasons_json"))
            except (TypeError,ValueError,json.JSONDecodeError): e["reasons"]=[]
            try: e["features"]=json.loads(e.pop("features_json"))
            except (TypeError,ValueError,json.JSONDecodeError): e["features"]={}
            out.append(e)
        return out

    def mark_early_event_consumed(self, event_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE early_events SET consumed=1 WHERE id=? AND consumed=0", (int(event_id),))

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            observations = db.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
            surge_events = db.execute(
                "SELECT COUNT(*) FROM move_events"
            ).fetchone()[0]
            total_row = db.execute(
                "SELECT value FROM observer_meta "
                "WHERE key='surge_events_total'"
            ).fetchone()
            surge_events_total = (
                int(total_row[0])
                if total_row is not None
                else int(surge_events)
            )

        return {
            "observations": int(observations),
            "surge_events": int(surge_events),
            "surge_events_total": int(surge_events_total),
        }

    def match(self, symbol: str, features: dict[str, Any], threshold: float | None = None, limit: int = 50) -> dict[str, Any]:
        clauses = ["symbol=?"]
        params: list[Any] = [symbol]
        if threshold is not None:
            clauses.append("threshold=?")
            params.append(float(threshold))
        with self._connect() as db:
            rows = db.execute(f"SELECT threshold, features_json FROM move_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
        if not rows:
            return {"matches": 0, "confidence": 0.0}
        numeric = ("volume", "oi", "iv", "delta", "gamma", "theta", "vega", "move_pct")
        scores = []
        for _, raw in rows:
            try:
                old = json.loads(raw)
                comparable = [k for k in numeric if features.get(k) is not None and old.get(k) is not None]
                if not comparable:
                    continue
                similarities = []
                for k in comparable:
                    a, b = float(features[k]), float(old[k])
                    scale = max(abs(a), abs(b), 1e-9)
                    similarities.append(max(0.0, 1.0 - abs(a - b) / scale))
                scores.append(sum(similarities) / len(similarities))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        confidence = round(min(1.0, (sum(scores) / len(scores)) if scores else 0.0), 4)
        return {"matches": len(scores), "confidence": confidence}


_observer = Tier1OptionObserver()


def observe_tier1_option_chains() -> list[dict[str, Any]]:
    return _observer.observe_all()


def get_tier1_option_observer() -> Tier1OptionObserver:
    return _observer
