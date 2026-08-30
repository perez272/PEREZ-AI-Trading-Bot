"""Fast option-move learning over already-acquired option-chain snapshots.

This engine NEVER calls a broker or market-data API.  The Tier-1 observer is
responsible for acquiring the genuine chain once; this engine consumes the
same snapshot, scores CE/PE contracts near the running value, learns which
features preceded large moves, and emits a compact strategy suggestion.

Move levels are observation/learning milestones, not profit guarantees.
Risk policy is hard-coded/configurable at 2% stop loss by default.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_PATH = Path(os.getenv("FAST_EXPIRY_MEMORY", "data/memory/fast_expiry_learning.sqlite3"))
MOVE_LEVELS = (5.0, 10.0, 50.0, 100.0, 150.0)
STRICT_STOP_LOSS_PCT = float(os.getenv("STRICT_OPTION_STOP_LOSS_PCT", "2.0"))
NEAR_ATM_PCT = float(os.getenv("FAST_EXPIRY_NEAR_ATM_PCT", "1.5"))
EARLY_SCORE_THRESHOLD = float(os.getenv("FAST_EXPIRY_EARLY_SCORE_THRESHOLD", "70"))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FastExpiryLearningEngine:
    """Learn from a chain already acquired by the market-data layer."""

    def __init__(self, db_path: Path = MEMORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pattern_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                option_type TEXT NOT NULL,
                expiry TEXT,
                strike REAL,
                spot REAL,
                ltp REAL NOT NULL,
                move_pct REAL NOT NULL,
                move_level REAL NOT NULL,
                near_atm INTEGER NOT NULL,
                expiry_bucket TEXT NOT NULL,
                feature_bucket TEXT NOT NULL,
                score REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                reasons_json TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_fast_symbol_ts ON pattern_events(symbol, observed_ts)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_fast_feature ON pattern_events(feature_bucket, move_level)")

    @staticmethod
    def _expiry_bucket(expiry: Any) -> str:
        text = str(expiry or "").strip()
        if not text:
            return "UNKNOWN"
        upper = text.upper()
        # Do not assume the exact calendar date format.  Explicit operator
        # metadata such as 0DTE/TODAY is accepted; otherwise keep the value.
        if any(token in upper for token in ("0DTE", "TODAY", "EXPIRY")):
            return "EXPIRY_DAY"
        return text[:16]

    @staticmethod
    def _option_market(option: dict[str, Any]) -> dict[str, Any]:
        return option.get("market_data") if isinstance(option.get("market_data"), dict) else {}

    @staticmethod
    def _option_features(option: dict[str, Any], market: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        greeks = option.get("option_greeks") if isinstance(option.get("option_greeks"), dict) else {}
        return (
            _f(market.get("volume")),
            _f(market.get("oi")),
            _f(greeks.get("iv")),
            _f(greeks.get("delta")),
            _f(greeks.get("gamma")),
            _f(greeks.get("theta")),
        )

    def _feature_bucket(self, market: dict[str, Any], greeks: dict[str, Any], move_pct: float) -> str:
        volume = _f(market.get("volume"))
        oi = _f(market.get("oi"))
        iv = _f(greeks.get("iv"))
        delta = abs(_f(greeks.get("delta")))
        return json.dumps({
            "volume": "HIGH" if volume >= 100000 else "MED" if volume >= 25000 else "LOW",
            "oi": "HIGH" if oi >= 250000 else "MED" if oi >= 50000 else "LOW",
            "iv": "HIGH" if iv >= 25 else "MED" if iv >= 15 else "LOW",
            "delta": "ATM" if delta >= 0.35 else "OTM",
            "move": "PRE50" if move_pct < 50 else "50PLUS",
        }, sort_keys=True, separators=(",", ":"))

    def analyze_chain(self, symbol: str, chain: list[dict[str, Any]], spot: float | None = None, observed_ts: str | None = None) -> list[dict[str, Any]]:
        """Analyze the supplied chain. No network/API calls occur here."""
        observed_ts = observed_ts or _now()
        spot_value = _f(spot)
        candidates: list[dict[str, Any]] = []

        for row in chain or []:
            if not isinstance(row, dict):
                continue
            strike = _f(row.get("strike_price"))
            if strike <= 0:
                continue
            near_atm = bool(spot_value > 0 and abs(strike - spot_value) / spot_value * 100.0 <= NEAR_ATM_PCT)
            if spot_value > 0 and not near_atm:
                # Keep a narrow band around the running value; this avoids
                # wasting decision time on distant strikes.
                continue
            for option_type in ("CE", "PE"):
                option = row.get("call_options" if option_type == "CE" else "put_options") or {}
                if not isinstance(option, dict) or not option.get("instrument_key"):
                    continue
                market = self._option_market(option)
                ltp = _f(market.get("ltp"))
                if ltp <= 0:
                    continue
                bid = _f(market.get("bid_price"))
                ask = _f(market.get("ask_price"))
                spread_pct = ((ask - bid) / ltp * 100.0) if bid > 0 and ask >= bid else 999.0
                greeks = option.get("option_greeks") if isinstance(option.get("option_greeks"), dict) else {}
                volume, oi, iv, delta, gamma, theta = self._option_features(option, market)

                # Current-chain move is relative to an optional prior value
                # supplied by the observer.  If absent, this remains a neutral
                # candidate rather than inventing a move.
                move_pct = _f(option.get("move_pct"), 0.0)
                velocity = _f(option.get("velocity_pct_per_min"), 0.0)
                acceleration = _f(option.get("acceleration_pct_per_min2"), 0.0)
                volume_ratio = _f(option.get("volume_ratio"), 0.0)

                score = 0.0
                reasons: list[str] = []
                if near_atm:
                    score += 20; reasons.append("near_running_value")
                if velocity >= 1.0:
                    score += 15; reasons.append("positive_velocity")
                if acceleration >= 0.5:
                    score += 20; reasons.append("acceleration")
                if volume_ratio >= 1.5:
                    score += 15; reasons.append("volume_expansion")
                elif volume_ratio >= 1.2:
                    score += 8; reasons.append("volume_support")
                if spread_pct <= 2.0:
                    score += 10; reasons.append("liquid_spread")
                elif spread_pct > 5.0:
                    score -= 20; reasons.append("wide_spread")
                if abs(delta) >= 0.35:
                    score += 8; reasons.append("responsive_delta")
                if gamma > 0:
                    score += 4; reasons.append("gamma_present")
                if iv > 25:
                    score += 3; reasons.append("high_iv")
                if theta < 0:
                    score += 2; reasons.append("theta_decay_present")

                expiry_bucket = self._expiry_bucket(row.get("expiry"))
                feature_bucket = self._feature_bucket(market, greeks, move_pct)
                score = round(max(0.0, min(100.0, score)), 2)
                if score < EARLY_SCORE_THRESHOLD:
                    continue

                level = max((x for x in MOVE_LEVELS if move_pct >= x), default=0.0)
                event = {
                    "type": "FAST_EXPIRY_CANDIDATE",
                    "symbol": symbol,
                    "option_type": option_type,
                    "instrument_key": option.get("instrument_key"),
                    "contract": option.get("trading_symbol") or row.get("trading_symbol"),
                    "expiry": row.get("expiry"),
                    "expiry_bucket": expiry_bucket,
                    "strike": strike,
                    "spot": spot_value,
                    "ltp": ltp,
                    "move_pct": round(move_pct, 4),
                    "milestone": level,
                    "near_atm": near_atm,
                    "volume": volume,
                    "oi": oi,
                    "iv": iv,
                    "delta": delta,
                    "gamma": gamma,
                    "theta": theta,
                    "spread_pct": round(spread_pct, 4),
                    "velocity_pct_per_min": velocity,
                    "acceleration_pct_per_min2": acceleration,
                    "volume_ratio": volume_ratio,
                    "score": score,
                    "strict_stop_loss_pct": STRICT_STOP_LOSS_PCT,
                    "reasons": reasons,
                    "strategy": "FAST_EXPIRY_MOMENTUM",
                    "suggestion": "PAPER_ENTRY_CANDIDATE" if score >= EARLY_SCORE_THRESHOLD else "WATCH",
                    "observed_ts": observed_ts,
                }
                candidates.append(event)

                if level >= 5.0:
                    with self._connect() as db:
                        db.execute(
                            """INSERT INTO pattern_events(
                            observed_ts,symbol,option_type,expiry,strike,spot,ltp,move_pct,
                            move_level,near_atm,expiry_bucket,feature_bucket,score,
                            stop_loss_pct,reasons_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (observed_ts, symbol, option_type, row.get("expiry"), strike,
                             spot_value, ltp, move_pct, level, int(near_atm), expiry_bucket,
                             feature_bucket, score, STRICT_STOP_LOSS_PCT,
                             json.dumps(reasons, separators=(",", ":"))),
                        )
        return sorted(candidates, key=lambda x: (x["score"], x["move_pct"]), reverse=True)

    def learn_summary(self, symbol: str | None = None) -> dict[str, Any]:
        with self._connect() as db:
            where = " WHERE symbol=?" if symbol else ""
            params = (symbol,) if symbol else ()
            total = int(db.execute(f"SELECT COUNT(*) FROM pattern_events{where}", params).fetchone()[0])
            rows = db.execute(
                f"SELECT move_level, expiry_bucket, feature_bucket FROM pattern_events{where} ORDER BY id DESC LIMIT 5000",
                params,
            ).fetchall()
        levels = Counter(float(row[0]) for row in rows)
        expiry = Counter(str(row[1]) for row in rows)
        features = Counter(str(row[2]) for row in rows)
        return {
            "observed_pattern_events": total,
            "milestones": {str(k): int(v) for k, v in sorted(levels.items())},
            "expiry_buckets": expiry.most_common(5),
            "top_feature_buckets": features.most_common(5),
            "strict_stop_loss_pct": STRICT_STOP_LOSS_PCT,
            "move_levels_pct": list(MOVE_LEVELS),
        }


_engine = FastExpiryLearningEngine()


def analyze_option_chain(symbol: str, chain: list[dict[str, Any]], spot: float | None = None, observed_ts: str | None = None) -> list[dict[str, Any]]:
    return _engine.analyze_chain(symbol, chain, spot, observed_ts)


def get_fast_expiry_learning_engine() -> FastExpiryLearningEngine:
    return _engine
