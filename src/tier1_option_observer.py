"""Continuous Tier-1 option observer using Angel One market data only.

The observer builds a small, rate-limit-safe option universe from the local
Angel instrument master and fetches fresh FULL quotes in one bulk request.
No synthetic prices and no alternate provider are used in the learning path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.broker.angel_client import AngelClient
from src.market_scanner import get_client
from src.option_chain import load_instruments
from src.explosive_move_detector import detect_explosive_move
from src.options_surge_engine import OptionsSurgeEngine
from src.expiry_learning_engine import record_surge_events
from src.move_memory import record_move

TIER1_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI")
MOVE_THRESHOLDS = (5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
MEMORY_PATH = Path(os.getenv("TIER1_OPTION_MEMORY", "data/memory/tier1_option_moves.sqlite3"))
BASELINE_TTL_SECONDS = int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS", "900"))
MAX_MEMORY_ROWS = int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS", "50000"))
HISTORY_POINTS = 16
MAX_OPTION_TOKENS = 48  # Angel FULL market-data API supports up to 50 tokens/request.
STRIKES_PER_SYMBOL = 4


class Tier1OptionObserver:
    def __init__(self, db_path: Path = MEMORY_PATH, angel_client: AngelClient | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._history = defaultdict(lambda: deque(maxlen=HISTORY_POINTS))
        self.surge_engine = OptionsSurgeEngine()
        self.angel_client = angel_client
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

    @staticmethod
    def _expiry_date(value: Any):
        from datetime import datetime
        try:
            return datetime.strptime(str(value).strip().upper(), "%d%b%Y").date()
        except (TypeError, ValueError):
            return None

    def _angel(self):
        if self.angel_client is None:
            self.angel_client = get_client()
        return self.angel_client

    def _select_contracts(self):
        """Select four nearest ATM-ish strikes per Tier-1 symbol for one bulk call."""
        from datetime import date
        grouped = defaultdict(list)
        for item in load_instruments():
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("name", "")).upper().strip()
            if symbol not in TIER1_SYMBOLS or str(item.get("exch_seg", "")).upper() != "NFO":
                continue
            if str(item.get("instrumenttype", "")).upper() not in {"OPTIDX", "OPTSTK"}:
                continue
            expiry = self._expiry_date(item.get("expiry"))
            token = str(item.get("token", "")).strip()
            option_symbol = str(item.get("symbol", "")).upper().strip()
            if expiry is None or expiry < date.today() or not token or not option_symbol.endswith(("CE", "PE")):
                continue
            try:
                strike = float(item.get("strike", 0)) / 100.0
            except (TypeError, ValueError):
                continue
            if strike <= 0:
                continue
            grouped[(symbol, expiry)].append({**item, "strike_value": strike})

        selected = []
        for symbol in TIER1_SYMBOLS:
            expiries = sorted({key[1] for key in grouped if key[0] == symbol})
            if not expiries:
                continue
            rows = grouped[(symbol, expiries[0])]
            strikes = sorted({float(r["strike_value"]) for r in rows})
            if not strikes:
                continue
            centre = strikes[len(strikes) // 2]
            chosen = sorted(strikes, key=lambda x: abs(x - centre))[:STRIKES_PER_SYMBOL]
            chosen_set = set(chosen)
            for row in rows:
                if row["strike_value"] in chosen_set:
                    selected.append(row)

        # Keep the bulk request within Angel's documented 50-token limit.
        return selected[:MAX_OPTION_TOKENS]

    @staticmethod
    def _quote_by_token(response: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(response, dict) or not response.get("status"):
            return {}
        fetched = (response.get("data") or {}).get("fetched", [])
        if not isinstance(fetched, list):
            return {}
        result = {}
        for quote in fetched:
            if not isinstance(quote, dict):
                continue
            token = str(quote.get("symbolToken") or quote.get("instrument_token") or quote.get("token") or "").strip()
            if token:
                result[token] = quote
        return result

    def _fresh_quote(self, quote: dict[str, Any], observed_ts: str) -> dict[str, Any] | None:
        try:
            ltp = float(quote.get("ltp", 0) or 0)
        except (TypeError, ValueError):
            return None
        if ltp <= 0:
            return None
        return {
            "ltp": ltp,
            "volume": float(quote.get("tradeVolume", quote.get("volume", 0)) or 0),
            "oi": float(quote.get("opnInterest", quote.get("oi", 0)) or 0),
            "percentChange": float(quote.get("percentChange", 0) or 0),
            "tradeTime": quote.get("exchTradeTime") or quote.get("exchangeFeedTime") or observed_ts,
        }

    def _fetch_angel_chain(self, contracts):
        if not contracts:
            return []
        tokens = [str(row.get("token", "")).strip() for row in contracts if row.get("token")]
        if not tokens:
            return []
        response = self._angel().get_market_data("FULL", {"NFO": tokens})
        quotes = self._quote_by_token(response)
        chain_by_symbol = {}
        observed_ts = datetime.now(timezone.utc).isoformat()
        for row in contracts:
            token = str(row.get("token", "")).strip()
            quote = self._fresh_quote(quotes.get(token, {}), observed_ts)
            if quote is None:
                continue
            symbol = str(row.get("name", "")).upper().strip()
            strike = float(row["strike_value"])
            expiry = str(row.get("expiry", "")).strip().upper()
            key = (symbol, expiry, strike)
            item = chain_by_symbol.setdefault(key, {"symbol": symbol, "expiry": expiry, "strike_price": strike})
            typ = "CE" if str(row.get("symbol", "")).upper().endswith("CE") else "PE"
            item["call_options" if typ == "CE" else "put_options"] = {
                "instrument_key": token,
                "trading_symbol": row.get("symbol", ""),
                "market_data": quote,
                "option_greeks": {},
            }
        return list(chain_by_symbol.values())

    def observe(self, symbol: str, chain: list[dict[str, Any]], observed_ts: str | None = None):
        if symbol not in TIER1_SYMBOLS:
            raise ValueError(f"Tier-1 observer rejected non-Tier-1 symbol: {symbol}")
        observed_ts = observed_ts or datetime.now(timezone.utc).isoformat()
        events = []
        valid = 0
        now = datetime.now(timezone.utc).timestamp()
        with self._connect() as db:
            for row in chain or []:
                for typ in ("CE", "PE"):
                    market = row.get("call_options" if typ == "CE" else "put_options") or {}
                    md = market.get("market_data") or {}
                    try:
                        ltp = float(md.get("ltp", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    key = str(market.get("instrument_key") or "").strip()
                    if ltp <= 0 or not key:
                        continue
                    valid += 1
                    snap = {"symbol": symbol, "option_type": typ, "instrument_key": key, "market_data": md, "option_greeks": market.get("option_greeks") or {}, "observed_ts": observed_ts}
                    fast = detect_explosive_move(symbol, typ, snap, list(self._history[key]))
                    self._history[key].append(snap)
                    if fast and fast.early:
                        events.append({"type": "EARLY_EXPLOSIVE", "symbol": symbol, "option_type": typ, "instrument_key": key, "current_ltp": fast.ltp, "move_1m_pct": fast.move_1m_pct, "move_3m_pct": fast.move_3m_pct, "move_5m_pct": fast.move_5m_pct, "score": fast.score, "observed_ts": observed_ts, "expiry": row.get("expiry")})
                    for e in self.surge_engine.observe(snap):
                        e["expiry"] = row.get("expiry")
                        e["data_source"] = "angel_one"
                        events.append({"type": "SURGE", **e})

                    raw = "|".join(str(x or "") for x in (symbol, typ, key, row.get("expiry"), row.get("strike_price")))
                    ck = hashlib.sha256(raw.encode()).hexdigest()
                    old = db.execute("SELECT baseline_ltp,baseline_ts FROM baselines WHERE contract_key=?", (ck,)).fetchone()
                    if not old:
                        db.execute("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?)", (ck, symbol, typ, row.get("expiry"), row.get("strike_price"), ltp, observed_ts, ltp, observed_ts))
                        continue
                    base, base_ts = old
                    try:
                        age = now - datetime.fromisoformat(str(base_ts).replace("Z", "+00:00")).timestamp()
                    except (ValueError, TypeError):
                        age = BASELINE_TTL_SECONDS + 1
                    if age > BASELINE_TTL_SECONDS or ltp < base * 0.5:
                        db.execute("UPDATE baselines SET baseline_ltp=?,baseline_ts=?,last_ltp=?,last_ts=? WHERE contract_key=?", (ltp, observed_ts, ltp, observed_ts, ck))
                        continue
                    move = (ltp - base) / base * 100 if base > 0 else 0
                    for threshold in MOVE_THRESHOLDS:
                        if move >= threshold:
                            features = {"symbol": symbol, "option_type": typ, "instrument_key": key, "contract": market.get("trading_symbol"), "expiry": row.get("expiry"), "strike": row.get("strike_price"), "move_pct": round(move, 4), "baseline_ltp": base, "ltp": ltp, "volume": md.get("volume"), "oi": md.get("oi"), "iv": (market.get("option_greeks") or {}).get("iv"), "data_source": "angel_one"}
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

    def observe_all(self):
        contracts = self._select_contracts()
        chain = self._fetch_angel_chain(contracts)
        grouped = defaultdict(list)
        for row in chain:
            grouped[str(row.get("symbol", "")).upper()].append(row)
        events = []
        for symbol, rows in grouped.items():
            try:
                events.extend(self.observe(symbol, rows))
            except Exception as exc:
                print(f"[TIER1 OBSERVER] {symbol}: {exc}")
        return events

    def stats(self):
        with self._connect() as db:
            return {"observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], "surge_events": db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0]}


_observer = Tier1OptionObserver()
def observe_tier1_option_chains():
    return _observer.observe_all()
def get_tier1_option_observer():
    return _observer
