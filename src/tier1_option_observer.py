"""Continuous Tier-1 option-chain observer and persistent move learner.

Observational only: never places or forces a trade. Persists successful chain
observations, rich option snapshots and move events so Telegram and research
can report genuine evidence.
"""
from __future__ import annotations
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/PEREZ-AI-Trading-Bot/.env')

import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.market_data_router import MarketDataRouter
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.explosive_move_detector import ExplosiveMoveSignal, detect_explosive_move
from src.ai_memory import remember_observation

TIER1_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI")
MOVE_THRESHOLDS = (5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
MEMORY_PATH = Path(os.getenv("TIER1_OPTION_MEMORY", "data/memory/tier1_option_moves.sqlite3"))
BASELINE_TTL_SECONDS = int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS", "900"))
MAX_MEMORY_ROWS = int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS", "50000"))
MAX_SNAPSHOT_ROWS = int(os.getenv("TIER1_OPTION_MAX_SNAPSHOT_ROWS", "50000"))
HISTORY_POINTS = 6


class Tier1OptionObserver:
    def __init__(self, db_path: Path = MEMORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=HISTORY_POINTS))
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
            db.execute("""CREATE TABLE IF NOT EXISTS raw_option_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_ts TEXT NOT NULL, symbol TEXT NOT NULL, option_type TEXT,
                instrument_key TEXT, contract TEXT, expiry TEXT, strike REAL,
                ltp REAL NOT NULL, features_json TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_move_symbol_threshold ON move_events(symbol, threshold)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations(observed_ts)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_raw_option_symbol_ts ON raw_option_snapshots(symbol, observed_ts)")

    @staticmethod
    def _contract_key(symbol: str, row: dict[str, Any], option_type: str) -> str:
        raw = "|".join(str(x or "") for x in (symbol, option_type, row.get("instrument_key"), row.get("expiry"), row.get("strike_price")))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _market(row: dict[str, Any], option_type: str) -> dict[str, Any]:
        return row.get("call_options" if option_type == "CE" else "put_options") or {}

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _rich_option(self, symbol: str, option_type: str, row: dict[str, Any], market: dict[str, Any],
                     chain_stats: dict[str, Any], observed_ts: str) -> tuple[dict[str, Any], dict[str, Any]]:
        md = market.get("market_data") or {}
        greeks = market.get("option_greeks") if isinstance(market.get("option_greeks"), dict) else {}
        strike = self._num(row.get("strike_price"), 0.0)
        spot = self._num(row.get("spot_ltp", row.get("underlying_ltp", row.get("underlying_price"))), 0.0)
        futures = self._num(row.get("futures_ltp", row.get("future_ltp", row.get("futures_price"))), 0.0)
        ltp = self._num(md.get("ltp"), 0.0)
        bid = self._num(md.get("bid_price", md.get("bid")), 0.0)
        ask = self._num(md.get("ask_price", md.get("ask")), 0.0)
        spread_pct = ((ask - bid) / ltp * 100.0) if ltp > 0 and ask >= bid > 0 else None
        distance = (strike - spot) if spot > 0 else None
        distance_pct = (distance / spot * 100.0) if spot > 0 and distance is not None else None
        expiry = row.get("expiry")
        minutes_to_expiry = None
        if expiry:
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%d/%m/%y"):
                try:
                    exp = datetime.strptime(str(expiry), fmt).replace(hour=15, minute=30, tzinfo=timezone.utc)
                    minutes_to_expiry = max(0.0, (exp - datetime.now(timezone.utc)).total_seconds() / 60.0)
                    break
                except ValueError:
                    continue
        feature = {
            "symbol": symbol, "option_type": option_type,
            "instrument_key": market.get("instrument_key"),
            "contract": market.get("trading_symbol") or row.get("trading_symbol"),
            "expiry": expiry, "strike": strike, "observed_ts": observed_ts,
            "ltp": ltp, "open": md.get("open"), "high": md.get("high"), "low": md.get("low"),
            "previous_close": md.get("previous_close"), "percent_change": md.get("percent_change"),
            "bid": bid, "ask": ask, "best_bid": bid, "best_ask": ask, "spread_pct": spread_pct,
            "volume": md.get("volume"), "avg_price": md.get("avg_price"),
            "oi": md.get("oi"), "open_interest": md.get("oi"), "oi_change": md.get("oi_change"),
            "oi_change_pct": md.get("oi_change_pct"),
            "iv": greeks.get("iv"), "delta": greeks.get("delta"), "gamma": greeks.get("gamma"),
            "theta": greeks.get("theta"), "vega": greeks.get("vega"), "rho": greeks.get("rho"),
            "spot_ltp": spot or None, "futures_ltp": futures or None,
            "distance_to_spot": distance, "distance_to_spot_pct": distance_pct,
            "atm_distance": abs(distance) if distance is not None else None,
            "ce_volume": chain_stats.get("ce_volume"), "pe_volume": chain_stats.get("pe_volume"),
            "ce_oi": chain_stats.get("ce_oi"), "pe_oi": chain_stats.get("pe_oi"),
            "ce_pe_volume_ratio": chain_stats.get("ce_pe_volume_ratio"),
            "ce_pe_oi_ratio": chain_stats.get("ce_pe_oi_ratio"),
            "minutes_to_expiry": minutes_to_expiry,
            "expiry_bucket": chain_stats.get("expiry_bucket", "UNKNOWN"),
            "live_market_data": True,
        }
        candidate = {
            "symbol": symbol, "option_type": option_type, "contract": feature["contract"],
            "expiry": expiry, "strike": strike, "ltp": ltp,
            "spot_ltp": spot or None, "futures_ltp": futures or None,
            "distance_to_spot": distance, "distance_to_spot_pct": distance_pct,
            "ce_pe_volume_ratio": chain_stats.get("ce_pe_volume_ratio"),
            "ce_pe_oi_ratio": chain_stats.get("ce_pe_oi_ratio"),
            "minutes_to_expiry": minutes_to_expiry,
            "expiry_bucket": chain_stats.get("expiry_bucket", "UNKNOWN"),
            "live_market_data": True,
        }
        return candidate, feature

    @staticmethod
    def _chain_stats(chain: list[dict[str, Any]]) -> dict[str, Any]:
        ce_volume = pe_volume = ce_oi = pe_oi = 0.0
        for row in chain or []:
            for option_type in ("CE", "PE"):
                market = row.get("call_options" if option_type == "CE" else "put_options") or {}
                md = market.get("market_data") or {}
                vol = Tier1OptionObserver._num(md.get("volume"), 0.0)
                oi = Tier1OptionObserver._num(md.get("oi"), 0.0)
                if option_type == "CE":
                    ce_volume += max(0.0, vol); ce_oi += max(0.0, oi)
                else:
                    pe_volume += max(0.0, vol); pe_oi += max(0.0, oi)
        return {
            "ce_volume": ce_volume, "pe_volume": pe_volume,
            "ce_oi": ce_oi, "pe_oi": pe_oi,
            "ce_pe_volume_ratio": ce_volume / pe_volume if pe_volume > 0 else None,
            "ce_pe_oi_ratio": ce_oi / pe_oi if pe_oi > 0 else None,
            "expiry_bucket": "UNKNOWN",
        }

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
            "volume": md.get("volume"), "oi": md.get("oi"), "oi_change": md.get("oi_change"),
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
        chain_stats = self._chain_stats(chain)
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
                    candidate, rich = self._rich_option(symbol, option_type, row, market, chain_stats, observed_ts)

                    db.execute(
                        "INSERT INTO raw_option_snapshots(observed_ts,symbol,option_type,instrument_key,contract,expiry,strike,ltp,features_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        (observed_ts, symbol, option_type, market.get("instrument_key"), rich.get("contract"),
                         row.get("expiry"), row.get("strike_price"), ltp, json.dumps(rich, default=str, separators=(",", ":")))
                    )

                    fast = self._record_fast_signal(symbol, option_type, market, observed_ts)
                    if fast and fast.early:
                        events.append({"type": "EARLY_EXPLOSIVE", "symbol": symbol, "option_type": option_type,
                                       "score": fast.score, "move_1m_pct": fast.move_1m_pct,
                                       "move_3m_pct": fast.move_3m_pct, "move_5m_pct": fast.move_5m_pct,
                                       "velocity": fast.velocity_pct_per_min, "acceleration": fast.acceleration_pct_per_min2,
                                       "volume_ratio": fast.volume_ratio, "spread_pct": fast.spread_pct,
                                       "reasons": list(fast.reasons), "instrument_key": fast.instrument_key, "ltp": fast.ltp})

                    key = self._contract_key(symbol, row, option_type)
                    existing = db.execute("SELECT baseline_ltp, baseline_ts, last_ltp FROM baselines WHERE contract_key=?", (key,)).fetchone()
                    if not existing:
                        db.execute("INSERT INTO baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (key, symbol, option_type, row.get("expiry"), row.get("strike_price"), ltp, observed_ts, ltp, observed_ts))
                    else:
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
                                db.execute("INSERT INTO move_events(event_key,symbol,option_type,contract,expiry,strike,threshold,baseline_ltp,ltp,move_pct,observed_ts,features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (event_key, symbol, option_type, features.get("contract"), row.get("expiry"), row.get("strike_price"), threshold, baseline, ltp, move_pct, observed_ts, json.dumps(features, separators=(",", ":"))))
                                events.append({"type": "THRESHOLD", "threshold": threshold, **features})
                            except sqlite3.IntegrityError:
                                pass
                        db.execute("UPDATE baselines SET last_ltp=?, last_ts=? WHERE contract_key=?", (ltp, observed_ts, key))
            if valid_contracts:
                db.execute("INSERT INTO observations(symbol,observed_ts,contracts_seen,events_count) VALUES (?,?,?,?)", (symbol, observed_ts, valid_contracts, len(events)))
            db.execute("DELETE FROM raw_option_snapshots WHERE id NOT IN (SELECT id FROM raw_option_snapshots ORDER BY id DESC LIMIT ?)", (MAX_SNAPSHOT_ROWS,))
            db.execute("DELETE FROM move_events WHERE id NOT IN (SELECT id FROM move_events ORDER BY id DESC LIMIT ?)", (MAX_MEMORY_ROWS,))
        return events

    def observe_all(self) -> list[dict[str, Any]]:
        """Angel-only observation path; observational/paper-only and fail-closed."""
        api_key = os.getenv("ANGEL_API_KEY")
        client_id = os.getenv("ANGEL_CLIENT_ID")
        password = os.getenv("ANGEL_PASSWORD")
        totp_secret = os.getenv("ANGEL_TOTP_SECRET")
        if not all((api_key, client_id, password, totp_secret)):
            print("[TIER1 ANGEL] credentials unavailable; fail closed")
            return []
        try:
            session = SessionManager(api_key, client_id, password, totp_secret)
            smartapi = session.get_client()
            angel = AngelClient(smartapi, session_manager=session)
            router = MarketDataRouter(angel)
            events: list[dict[str, Any]] = []
            status = angel.market_data_status()
            print(f"[TIER1 ANGEL] authenticated={bool(smartapi)} cooldown={status.get('cooldown_remaining', 0)} remaining={status.get('requests_remaining', 0)}")
            for symbol in TIER1_SYMBOLS:
                chain, source = router.get_option_chain(symbol)
                if source != "angel_one" or not chain:
                    print(f"[TIER1 ANGEL] {symbol}: no verified Angel option chain; skipped safely")
                    continue
                observed = self.observe(symbol, chain)
                events.extend(observed)
                chain_stats = self._chain_stats(chain)
                for row in chain:
                    for option_type in ("CE", "PE"):
                        market = self._market(row, option_type)
                        md = market.get("market_data") or {}
                        try:
                            ltp = float(md.get("ltp", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                        if ltp <= 0:
                            continue
                        candidate, rich = self._rich_option(symbol, option_type, row, market, chain_stats, datetime.now(timezone.utc).isoformat())
                        try:
                            remember_observation(candidate, options_result=rich)
                        except Exception as exc:
                            print(f"[TIER1 MEMORY] observation skipped safely: {exc}")
                print(f"[TIER1 ANGEL] {symbol}: contracts={len(chain)} events={len(observed)}")
            return events
        except Exception as exc:
            print(f"[TIER1 ANGEL] cycle failed safely: {exc}")
            return []

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            observations = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            snapshots = db.execute("SELECT COUNT(*) FROM raw_option_snapshots").fetchone()[0]
            surge_events = db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0]
        return {"observations": int(observations), "snapshots": int(snapshots), "surge_events": int(surge_events), "wins": 0, "win_rate": 0.0}

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
        numeric = ("volume", "oi", "iv", "delta", "gamma", "theta", "vega", "move_pct", "spot_ltp", "futures_ltp", "distance_to_spot_pct")
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
