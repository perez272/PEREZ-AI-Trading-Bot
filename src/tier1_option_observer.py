"""Continuous Tier-1 option observer using Angel One market data only."""
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

from src.explosive_move_detector import detect_explosive_move
from src.options_surge_engine import OptionsSurgeEngine
from src.expiry_learning_engine import record_surge_events
from src.move_memory import record_move
from src.market_scanner import get_client
from src.option_chain import load_instruments

TIER1_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI")
MOVE_THRESHOLDS = (5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
MEMORY_PATH = Path(os.getenv("TIER1_OPTION_MEMORY", "data/memory/tier1_option_moves.sqlite3"))
CANDLE_CACHE_FILE = Path(os.getenv("PEREZ_CANDLE_CACHE_FILE", "/tmp/perez_ai_candle_cache.json"))
BASELINE_TTL_SECONDS = int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS", "900"))
MAX_MEMORY_ROWS = int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS", "50000"))
HISTORY_POINTS = 16
OPTION_CONTRACTS_PER_SYMBOL = 4
OPTION_CACHE_MAX_AGE_SECONDS = int(os.getenv("TIER1_OPTION_SPOT_MAX_AGE_SECONDS", "300"))


class Tier1OptionObserver:
    """Read fresh Angel One quotes once per cycle and feed learning engines."""

    def __init__(self, db_path: Path = MEMORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._history = defaultdict(lambda: deque(maxlen=HISTORY_POINTS))
        self.surge_engine = OptionsSurgeEngine()
        self._init_db()

    def _connect(self):
        c = sqlite3.connect(self.db_path)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_db(self):
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS baselines (contract_key TEXT PRIMARY KEY,symbol TEXT NOT NULL,option_type TEXT,expiry TEXT,strike REAL,baseline_ltp REAL NOT NULL,baseline_ts TEXT NOT NULL,last_ltp REAL NOT NULL,last_ts TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS move_events (id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,option_type TEXT,contract TEXT,expiry TEXT,strike REAL,threshold REAL NOT NULL,baseline_ltp REAL NOT NULL,ltp REAL NOT NULL,move_pct REAL NOT NULL,observed_ts TEXT NOT NULL,features_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,observed_ts TEXT NOT NULL,contracts_seen INTEGER NOT NULL,events_count INTEGER NOT NULL DEFAULT 0)")

    def observe(self, symbol: str, chain: list[dict[str, Any]], observed_ts: str | None = None):
        if symbol not in TIER1_SYMBOLS:
            raise ValueError(f"Tier-1 observer rejected non-Tier-1 symbol: {symbol}")
        observed_ts = observed_ts or datetime.now(timezone.utc).isoformat()
        events = []
        valid = 0
        now = time.time()
        with self._connect() as db:
            for row in chain or []:
                for typ in ("CE", "PE"):
                    market = row.get("call_options" if typ == "CE" else "put_options") or {}
                    md = market.get("market_data") or {}
                    try:
                        ltp = float(md.get("ltp", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    key = str(market.get("instrument_key") or "")
                    if ltp <= 0 or not key:
                        continue
                    valid += 1
                    snap = {
                        "symbol": symbol,
                        "option_type": typ,
                        "instrument_key": key,
                        "market_data": md,
                        "option_greeks": market.get("option_greeks") or {},
                        "observed_ts": observed_ts,
                    }
                    fast = detect_explosive_move(symbol, typ, snap, list(self._history[key]))
                    self._history[key].append(snap)
                    if fast and fast.early:
                        events.append({"type": "EARLY_EXPLOSIVE", "symbol": symbol, "option_type": typ, "instrument_key": key, "current_ltp": fast.ltp, "move_1m_pct": fast.move_1m_pct, "move_3m_pct": fast.move_3m_pct, "move_5m_pct": fast.move_5m_pct, "score": fast.score, "observed_ts": observed_ts, "expiry": row.get("expiry")})
                    surge = self.surge_engine.observe(snap)
                    for e in surge:
                        e["expiry"] = row.get("expiry")
                        events.append({"type": "SURGE", **e})

                    raw = "|".join(str(x or "") for x in (symbol, typ, key, row.get("expiry"), row.get("strike_price")))
                    ck = hashlib.sha256(raw.encode()).hexdigest()
                    old = db.execute("SELECT baseline_ltp,baseline_ts FROM baselines WHERE contract_key=?", (ck,)).fetchone()
                    if not old:
                        db.execute("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?)", (ck, symbol, typ, row.get("expiry"), row.get("strike_price"), ltp, observed_ts, ltp, observed_ts))
                        continue
                    base, base_ts = old
                    try:
                        age = now - datetime.fromisoformat(base_ts).timestamp()
                    except (ValueError, TypeError):
                        age = BASELINE_TTL_SECONDS + 1
                    if age > BASELINE_TTL_SECONDS or ltp < base * 0.5:
                        db.execute("UPDATE baselines SET baseline_ltp=?,baseline_ts=?,last_ltp=?,last_ts=? WHERE contract_key=?", (ltp, observed_ts, ltp, observed_ts, ck))
                        continue
                    move = (ltp - base) / base * 100 if base > 0 else 0
                    for threshold in MOVE_THRESHOLDS:
                        if move >= threshold:
                            features = {"symbol": symbol, "option_type": typ, "instrument_key": key, "contract": market.get("trading_symbol"), "expiry": row.get("expiry"), "strike": row.get("strike_price"), "move_pct": round(move, 4), "baseline_ltp": base, "ltp": ltp, "volume": md.get("volume"), "oi": md.get("oi"), "iv": (market.get("option_greeks") or {}).get("iv")}
                            ek = f"{ck}|{threshold}|{observed_ts[:16]}"
                            try:
                                db.execute("INSERT INTO move_events(event_key,symbol,option_type,contract,expiry,strike,threshold,baseline_ltp,ltp,move_pct,observed_ts,features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (ek, symbol, typ, features["contract"], features["expiry"], features["strike"], threshold, base, ltp, move, observed_ts, json.dumps(features, separators=(",", ":"))))
                                events.append({"type": "THRESHOLD", "threshold": threshold, **features})
                            except sqlite3.IntegrityError:
                                pass
                    db.execute("UPDATE baselines SET last_ltp=?,last_ts=? WHERE contract_key=?", (ltp, observed_ts, ck))
            if valid:
                db.execute("INSERT INTO observations(symbol,observed_ts,contracts_seen,events_count) VALUES(?,?,?,?)", (symbol, observed_ts, valid, len(events)))
            db.execute("DELETE FROM move_events WHERE id NOT IN (SELECT id FROM move_events ORDER BY id DESC LIMIT ?)", (MAX_MEMORY_ROWS,))

        canonical = [e for e in events if e.get("type") in {"SURGE", "THRESHOLD"}]
        if canonical:
            record_surge_events(canonical)
            for e in canonical:
                if e.get("type") == "THRESHOLD":
                    record_move({**e, "percent_change": e.get("move_pct")})
        return events

    @staticmethod
    def _fresh_spots() -> dict[str, float]:
        """Use only the scanner's last validated Angel One candle cache."""
        try:
            payload = json.loads(CANDLE_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        now = datetime.now(timezone.utc).timestamp()
        spots: dict[str, float] = {}
        for symbol in TIER1_SYMBOLS:
            entry = payload.get(symbol) if isinstance(payload, dict) else None
            if not isinstance(entry, dict) or entry.get("source") != "angel_one":
                continue
            candles = entry.get("candles")
            bucket = entry.get("bucket")
            if not isinstance(candles, list) or not candles or not bucket:
                continue
            try:
                ts = datetime.fromisoformat(str(bucket).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = now - ts.timestamp()
                close = float(candles[-1][4])
            except (TypeError, ValueError, IndexError):
                continue
            if close > 0 and -60 <= age <= OPTION_CACHE_MAX_AGE_SECONDS:
                spots[symbol] = close
        return spots

    @staticmethod
    def _select_contracts(spots: dict[str, float]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        instruments = load_instruments()
        today = datetime.now().date()
        selected: list[dict[str, Any]] = []
        meta: dict[str, dict[str, Any]] = {}
        for symbol, spot in spots.items():
            candidates = []
            for item in instruments:
                if str(item.get("name", "")).upper().strip() != symbol or str(item.get("exch_seg", "")).upper().strip() != "NFO":
                    continue
                if str(item.get("instrumenttype", "")).upper().strip() not in {"OPTIDX", "OPTSTK"}:
                    continue
                expiry_text = str(item.get("expiry", "")).strip().upper()
                try:
                    expiry = datetime.strptime(expiry_text, "%d%b%Y").date()
                    strike = float(item.get("strike", 0)) / 100.0
                except (TypeError, ValueError):
                    continue
                if expiry < today or strike <= 0:
                    continue
                option_type = "CE" if str(item.get("symbol", "")).upper().endswith("CE") else "PE" if str(item.get("symbol", "")).upper().endswith("PE") else ""
                token = str(item.get("token", "")).strip()
                if not option_type or not token:
                    continue
                candidates.append((expiry, abs(strike - spot), strike, option_type, token, str(item.get("symbol", ""))))
            if not candidates:
                continue
            nearest_expiry = min(x[0] for x in candidates)
            near = [x for x in candidates if x[0] == nearest_expiry]
            for typ in ("CE", "PE"):
                for item in sorted((x for x in near if x[3] == typ), key=lambda x: x[1])[: OPTION_CONTRACTS_PER_SYMBOL // 2]:
                    _, _, strike, _, token, trading_symbol = item
                    selected.append({"exchange": "NFO", "token": token})
                    meta[token] = {"symbol": symbol, "option_type": typ, "expiry": nearest_expiry.strftime("%d%b%Y"), "strike": strike, "trading_symbol": trading_symbol}
        return selected, meta

    def observe_all(self):
        """Fetch one batched Angel FULL quote request for the Tier-1 option set."""
        spots = self._fresh_spots()
        if not spots:
            print("[TIER1 OBSERVER] no fresh Angel One underlying candles available")
            return []
        contracts, meta = self._select_contracts(spots)
        if not contracts:
            print("[TIER1 OBSERVER] no valid Angel One NFO contracts selected")
            return []
        tokens = [c["token"] for c in contracts]
        try:
            response = get_client().get_market_data("FULL", {"NFO": tokens[:50]})
        except Exception as exc:
            print(f"[TIER1 OBSERVER] Angel One option quote request failed: {exc}")
            return []
        if not isinstance(response, dict) or not response.get("status"):
            print("[TIER1 OBSERVER] Angel One returned no valid option data")
            return []
        fetched = (response.get("data") or {}).get("fetched") or []
        received = datetime.now(timezone.utc).isoformat()
        chains: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for quote in fetched:
            if not isinstance(quote, dict):
                continue
            token = str(quote.get("symbolToken") or quote.get("symboltoken") or "").strip()
            info = meta.get(token)
            if not info:
                continue
            try:
                ltp = float(quote.get("ltp") or 0)
            except (TypeError, ValueError):
                continue
            if ltp <= 0:
                continue
            md = {
                "ltp": ltp,
                "volume": quote.get("tradeVolume", quote.get("volume", 0)),
                "oi": quote.get("opnInterest", quote.get("oi", 0)),
                "exchangeFeedTime": quote.get("exchFeedTime") or quote.get("exchangeFeedTime"),
                "timestamp": quote.get("exchTradeTime") or quote.get("exchangeTradeTime"),
                "symbolToken": token,
            }
            field = "call_options" if info["option_type"] == "CE" else "put_options"
            row = {"expiry": info["expiry"], "strike_price": info["strike"], field: {"instrument_key": f"NFO|{token}", "trading_symbol": info["trading_symbol"], "market_data": md, "option_greeks": {}}}
            chains[info["symbol"]].append(row)
        events = []
        for symbol, chain in chains.items():
            events.extend(self.observe(symbol, chain, received))
        print(f"[TIER1 OBSERVER] Angel One: quotes={sum(len(v) for v in chains.values())} events={len(events)}")
        return events

    def stats(self):
        with self._connect() as db:
            return {"observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], "surge_events": db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0]}


_observer = Tier1OptionObserver()


def observe_tier1_option_chains():
    return _observer.observe_all()


def get_tier1_option_observer():
    return _observer
