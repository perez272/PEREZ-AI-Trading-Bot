"""Validated 5/10/15-minute option surge detection.

Observational only: never places orders. Live events are emitted only from a
fresh positive-LTP snapshot. Older observations may be retained briefly as
window baselines, but they can never themselves trigger a surge event.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable

WINDOWS = (5, 10, 15)
SURGE_PCT = 5.0
BASELINE_TOLERANCE_SECONDS = 90


@dataclass(frozen=True)
class SurgeEvent:
    symbol: str
    option_type: str
    instrument_key: str
    window_minutes: int
    move_pct: float
    current_ltp: float
    baseline_ltp: float
    observed_ts: str
    volume: float = 0.0
    oi: float = 0.0
    iv: float = 0.0


class OptionsSurgeEngine:
    def __init__(self, threshold_pct: float = SURGE_PCT, max_age_seconds: int = 120,
                 clock: Callable[[], datetime] | None = None):
        self.threshold_pct = float(threshold_pct)
        self.max_age_seconds = int(max_age_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _num(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _ts(value: Any) -> datetime | None:
        try:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _snapshot(self, snapshot: dict[str, Any]) -> tuple[dict[str, Any] | None, datetime | None, float]:
        md = snapshot.get("market_data") or snapshot
        ltp = self._num(md.get("ltp"))
        key = str(snapshot.get("instrument_key") or md.get("instrument_key") or "").strip()
        dt = self._ts(snapshot.get("observed_ts") or snapshot.get("timestamp"))
        if ltp <= 0 or not key or dt is None:
            return None, None, 0.0
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age = (now - dt).total_seconds()
        return {
            "ts": dt,
            "ltp": ltp,
            "volume": self._num(md.get("volume")),
            "oi": self._num(md.get("oi")),
            "iv": self._num((snapshot.get("option_greeks") or {}).get("iv")),
        }, dt, age

    def _valid(self, snapshot: dict[str, Any]) -> tuple[bool, datetime | None]:
        """Validate the *current* observation freshness gate."""
        _, dt, age = self._snapshot(snapshot)
        if dt is None:
            return False, None
        if age > self.max_age_seconds or age < -30:
            return False, None
        return True, dt

    def observe(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        current, dt, age = self._snapshot(snapshot)
        if current is None or dt is None or age < -30:
            return []

        # Retain at most the data needed to form a 15-minute baseline plus the
        # tolerance. This permits deterministic/backfilled tests and late
        # observations to seed history without allowing stale data to trigger.
        if age > self.max_age_seconds + 15 * 60 + BASELINE_TOLERANCE_SECONDS:
            return []

        key = str(snapshot.get("instrument_key") or (snapshot.get("market_data") or {}).get("instrument_key") or "").strip()
        history = self._history.setdefault(key, [])
        history.append(current)
        cutoff = dt.timestamp() - 15 * 60 - BASELINE_TOLERANCE_SECONDS
        self._history[key] = [x for x in history if x["ts"].timestamp() >= cutoff][-30:]
        history = self._history[key]

        # A stale observation is baseline material only. Never emit a live
        # event from it.
        if age > self.max_age_seconds:
            return []

        events: list[dict[str, Any]] = []
        for minutes in WINDOWS:
            target = dt.timestamp() - minutes * 60
            eligible = [x for x in history if x["ts"].timestamp() <= target]
            if not eligible:
                continue
            baseline = min(eligible, key=lambda x: abs(x["ts"].timestamp() - target))
            if abs(baseline["ts"].timestamp() - target) > BASELINE_TOLERANCE_SECONDS:
                continue
            move = ((current["ltp"] - baseline["ltp"]) / baseline["ltp"] * 100.0
                    if baseline["ltp"] > 0 else 0.0)
            if move >= self.threshold_pct:
                event = SurgeEvent(
                    str(snapshot.get("symbol", "")),
                    str(snapshot.get("option_type", "")).upper(),
                    key,
                    minutes,
                    round(move, 4),
                    current["ltp"],
                    baseline["ltp"],
                    dt.isoformat(),
                    current["volume"],
                    current["oi"],
                    current["iv"],
                )
                events.append(asdict(event))
        return events

    def observe_chain(self, symbol: str, chain: list[dict[str, Any]], observed_ts: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for row in chain or []:
            for option_type, field in (("CE", "call_options"), ("PE", "put_options")):
                market = row.get(field) or {}
                md = market.get("market_data") or {}
                if self._num(md.get("ltp")) <= 0 or not market.get("instrument_key"):
                    continue
                events.extend(self.observe({
                    "symbol": symbol,
                    "option_type": option_type,
                    "instrument_key": market.get("instrument_key"),
                    "market_data": md,
                    "option_greeks": market.get("option_greeks") or {},
                    "observed_ts": observed_ts,
                }))
        return events
