"""Paper-only Upstox option-chain snapshot collector for short-covering research.

This module is deliberately standalone: it stores timestamped observations and
compares consecutive polls. It does not place orders or connect to bot services.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_DB = Path("data/short_covering_observations.sqlite3")
DEFAULT_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
IST = timezone(timedelta(hours=5, minutes=30))


class ShortCoveringSnapshotCollector:
    """Capture one option-chain poll and evaluate contracts against prior polls.

    Upstox `prev_oi` is intentionally ignored: it is previous-session OI.
    Intraday OI changes are calculated only from this collector's own snapshots.
    Volume is cumulative for the session, so interval volume is the difference
    between consecutive cumulative readings.
    """

    def __init__(
        self,
        client: Any,
        db_path: str | Path = DEFAULT_DB,
        *,
        oi_drop_threshold: float = -15.0,
        price_spike_threshold: float = 20.0,
        volume_multiplier: float = 2.5,
        min_volume_baseline_intervals: int = 5,
        min_interval_seconds: int = 15,
        max_interval_seconds: int = 180,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not math.isfinite(oi_drop_threshold) or oi_drop_threshold >= 0:
            raise ValueError("oi_drop_threshold must be finite and negative")
        if not math.isfinite(price_spike_threshold) or price_spike_threshold < 0:
            raise ValueError("price_spike_threshold must be finite and non-negative")
        if not math.isfinite(volume_multiplier) or volume_multiplier <= 0:
            raise ValueError("volume_multiplier must be finite and positive")
        if min_volume_baseline_intervals < 3:
            raise ValueError("at least 3 historical volume intervals are required")
        if min_interval_seconds < 1 or max_interval_seconds <= min_interval_seconds:
            raise ValueError("invalid snapshot interval bounds")
        self.client = client
        self.db_path = Path(db_path)
        self.oi_drop_threshold = float(oi_drop_threshold)
        self.price_spike_threshold = float(price_spike_threshold)
        self.volume_multiplier = float(volume_multiplier)
        self.min_volume_baseline_intervals = int(min_volume_baseline_intervals)
        self.min_interval_seconds = int(min_interval_seconds)
        self.max_interval_seconds = int(max_interval_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS short_covering_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    trading_date_ist TEXT,
                    symbol TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    instrument_key TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
                    ltp REAL NOT NULL,
                    oi REAL NOT NULL,
                    cumulative_volume REAL NOT NULL,
                    bid REAL,
                    ask REAL,
                    underlying_spot REAL,
                    UNIQUE(captured_at, symbol, expiry, instrument_key)
                )
                """
            )
            columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(short_covering_observations)"
                ).fetchall()
            }
            if "trading_date_ist" not in columns:
                conn.execute(
                    "ALTER TABLE short_covering_observations ADD COLUMN trading_date_ist TEXT"
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_short_covering_contract_time
                ON short_covering_observations
                (symbol, expiry, instrument_key, trading_date_ist, captured_at DESC)
                """
            )

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _option_leg(row: dict[str, Any], option_type: str) -> dict[str, Any]:
        raw = row.get("call_options" if option_type == "CE" else "put_options") or {}
        if not isinstance(raw, dict):
            return {}
        market = raw.get("market_data")
        return market if isinstance(market, dict) else raw

    def _records(self, chain: list[dict[str, Any]], symbol: str, captured_at: str,
                 requested_expiry: str | None) -> tuple[list[tuple[Any, ...]], int]:
        records: list[tuple[Any, ...]] = []
        skipped = 0
        for row in chain:
            if not isinstance(row, dict):
                skipped += 1
                continue
            expiry = str(row.get("expiry") or requested_expiry or "").strip()
            if not expiry or (requested_expiry and expiry != requested_expiry):
                skipped += 1
                continue
            spot = self._number(row.get("underlying_spot_price"))
            strike = self._number(row.get("strike_price"))
            if strike is None or strike <= 0:
                skipped += 1
                continue
            for option_type in ("CE", "PE"):
                leg_key = "call_options" if option_type == "CE" else "put_options"
                leg = row.get(leg_key) or {}
                if not isinstance(leg, dict):
                    skipped += 1
                    continue
                instrument_key = str(leg.get("instrument_key") or "").strip()
                market = self._option_leg(row, option_type)
                ltp = self._number(market.get("ltp"))
                oi = self._number(market.get("oi"))
                volume = self._number(market.get("volume"))
                bid = self._number(market.get("bid_price"))
                ask = self._number(market.get("ask_price"))
                if (
                    not instrument_key or ltp is None or ltp <= 0
                    or oi is None or oi < 0
                    or volume is None or volume < 0
                ):
                    skipped += 1
                    continue
                if bid is not None and bid < 0:
                    bid = None
                if ask is not None and ask < 0:
                    ask = None
                records.append((
                    captured_at, symbol, expiry, instrument_key, strike,
                    option_type, ltp, oi, volume, bid, ask, spot,
                ))
        return records, skipped

    def _analyse_contract(self, conn: sqlite3.Connection, symbol: str,
                          expiry: str, instrument_key: str,
                          trading_date_ist: str) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT captured_at, strike, option_type, ltp, oi, cumulative_volume
            FROM short_covering_observations
            WHERE symbol=? AND expiry=? AND instrument_key=?
              AND trading_date_ist=?
            ORDER BY captured_at DESC LIMIT ?
            """,
            (symbol, expiry, instrument_key, trading_date_ist,
             self.min_volume_baseline_intervals + 2),
        ).fetchall()
        base = {
            "symbol": symbol, "expiry": expiry, "instrument_key": instrument_key,
            "signal": False,
        }
        needed = self.min_volume_baseline_intervals + 2
        if len(rows) < needed:
            return {**base, "reason": "INSUFFICIENT_SNAPSHOT_HISTORY"}
        ordered = list(reversed(rows))
        intervals: list[float] = []
        for older, newer in zip(ordered, ordered[1:]):
            try:
                t0 = datetime.fromisoformat(older["captured_at"])
                t1 = datetime.fromisoformat(newer["captured_at"])
                gap = (t1 - t0).total_seconds()
            except (TypeError, ValueError):
                return {**base, "reason": "INVALID_SNAPSHOT_TIMESTAMP"}
            if gap < self.min_interval_seconds or gap > self.max_interval_seconds:
                return {**base, "reason": "SNAPSHOT_INTERVAL_OUT_OF_RANGE"}
            delta = float(newer["cumulative_volume"]) - float(older["cumulative_volume"])
            if delta < 0:
                return {**base, "reason": "CUMULATIVE_VOLUME_RESET_OR_CORRUPT"}
            intervals.append(delta)

        previous = ordered[-2]
        current = ordered[-1]
        previous_oi = float(previous["oi"])
        previous_ltp = float(previous["ltp"])
        if previous_oi <= 0 or previous_ltp <= 0:
            return {**base, "reason": "INVALID_PREVIOUS_OI_OR_PRICE"}
        oi_change = (float(current["oi"]) - previous_oi) / previous_oi * 100.0
        price_change = (float(current["ltp"]) - previous_ltp) / previous_ltp * 100.0
        historical_volumes = intervals[:-1]
        baseline = statistics.median(historical_volumes)
        current_volume = intervals[-1]
        if baseline <= 0:
            return {
                **base, "reason": "ZERO_HISTORICAL_INTERVAL_VOLUME",
                "oi_change_pct": round(oi_change, 3),
                "price_change_pct": round(price_change, 3),
                "interval_volume": current_volume,
            }
        volume_ratio = current_volume / baseline
        conditions = (
            oi_change <= self.oi_drop_threshold
            and price_change >= self.price_spike_threshold
            and volume_ratio >= self.volume_multiplier
        )
        return {
            **base,
            "strike": float(current["strike"]),
            "option_type": str(current["option_type"]),
            "oi_change_pct": round(oi_change, 3),
            "price_change_pct": round(price_change, 3),
            "interval_volume": current_volume,
            "historical_interval_volume_median": round(baseline, 3),
            "volume_ratio": round(volume_ratio, 3),
            "signal": bool(conditions),
            "reason": (
                "PRICE_UP_INTRADAY_OI_DOWN_VOLUME_EXPANSION"
                if conditions else "THRESHOLDS_NOT_ALL_MET"
            ),
            "interpretation": (
                "INTRADAY_SHORT_COVERING_EVIDENCE_ONLY"
                if conditions else "NOT_CONFIRMED"
            ),
        }

    def capture(self, symbol: str, expiry: str | None = None) -> dict[str, Any]:
        """Fetch and persist one chain snapshot; never loops or submits orders."""
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        chain = self.client.get_option_chain(normalized_symbol, expiry=expiry)
        if not isinstance(chain, list) or not chain:
            raise RuntimeError(f"No Upstox option chain returned for {normalized_symbol}")
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        captured_at = now.astimezone(timezone.utc).isoformat(timespec="microseconds")
        trading_date_ist = now.astimezone(IST).date().isoformat()
        records, skipped = self._records(chain, normalized_symbol, captured_at, expiry)
        if not records:
            raise RuntimeError(f"No valid option contracts in {normalized_symbol} chain")
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO short_covering_observations
                (captured_at, trading_date_ist, symbol, expiry, instrument_key,
                 strike, option_type, ltp, oi, cumulative_volume, bid, ask,
                 underlying_spot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (record[0], trading_date_ist, *record[1:])
                    for record in records
                ],
            )
            analyses = [
                self._analyse_contract(
                    conn, normalized_symbol, row[2], row[3], trading_date_ist
                )
                for row in records
            ]
        signals = [item for item in analyses if item.get("signal")]
        return {
            "symbol": normalized_symbol,
            "captured_at": captured_at,
            "contracts_saved": len(records),
            "contracts_skipped": skipped,
            "contracts_evaluated": sum(
                item.get("reason") != "INSUFFICIENT_SNAPSHOT_HISTORY"
                for item in analyses
            ),
            "signals": signals,
            "analysis": analyses,
            "database": str(self.db_path),
            "mode": "OBSERVATION_ONLY",
        }
