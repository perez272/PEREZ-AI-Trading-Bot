"""Validated 5/10/15-minute option surge detection.

Observational only: never places orders. Input must be fresh, positive-LTP
option snapshots carrying a stable contract key and UTC observation time.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

WINDOWS = (5, 10, 15)
SURGE_PCT = 5.0

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
    def __init__(self, threshold_pct: float = SURGE_PCT, max_age_seconds: int = 120):
        self.threshold_pct = float(threshold_pct)
        self.max_age_seconds = int(max_age_seconds)
        self._history: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _num(value: Any) -> float:
        try: return float(value or 0.0)
        except (TypeError, ValueError): return 0.0

    @staticmethod
    def _ts(value: Any) -> datetime | None:
        try:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError): return None

    def _valid(self, snapshot: dict[str, Any]) -> tuple[bool, datetime | None]:
        md = snapshot.get("market_data") or snapshot
        ltp = self._num(md.get("ltp"))
        key = str(snapshot.get("instrument_key") or md.get("instrument_key") or "").strip()
        dt = self._ts(snapshot.get("observed_ts") or snapshot.get("timestamp"))
        if ltp <= 0 or not key or dt is None: return False, None
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        if age > self.max_age_seconds or age < -30: return False, None
        return True, dt

    def observe(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        ok, dt = self._valid(snapshot)
        if not ok: return []
        md = snapshot.get("market_data") or snapshot
        key = str(snapshot.get("instrument_key") or md.get("instrument_key"))
        history = self._history.setdefault(key, [])
        current = {"ts": dt, "ltp": self._num(md.get("ltp")), "volume": self._num(md.get("volume")), "oi": self._num(md.get("oi")), "iv": self._num((snapshot.get("option_greeks") or {}).get("iv"))}
        history.append(current)
        cutoff = dt.timestamp() - 15 * 60 - 30
        self._history[key] = [x for x in history if x["ts"].timestamp() >= cutoff][-30:]
        history = self._history[key]
        events: list[dict[str, Any]] = []
        for minutes in WINDOWS:
            target = dt.timestamp() - minutes * 60
            eligible = [x for x in history if x["ts"].timestamp() <= target]
            if not eligible: continue
            baseline = min(eligible, key=lambda x: abs(x["ts"].timestamp() - target))
            if abs(baseline["ts"].timestamp() - target) > 90: continue
            move = (current["ltp"] - baseline["ltp"]) / baseline["ltp"] * 100.0 if baseline["ltp"] > 0 else 0.0
            if move >= self.threshold_pct:
                event = SurgeEvent(str(snapshot.get("symbol", "")), str(snapshot.get("option_type", "")).upper(), key, minutes, round(move, 4), current["ltp"], baseline["ltp"], dt.isoformat(), current["volume"], current["oi"], current["iv"])
                events.append(asdict(event))
        return events

    def observe_chain(self, symbol: str, chain: list[dict[str, Any]], observed_ts: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for row in chain or []:
            for option_type, field in (("CE", "call_options"), ("PE", "put_options")):
                market = row.get(field) or {}
                md = market.get("market_data") or {}
                if self._num(md.get("ltp")) <= 0 or not market.get("instrument_key"): continue
                events.extend(self.observe({"symbol": symbol, "option_type": option_type, "instrument_key": market.get("instrument_key"), "market_data": md, "option_greeks": market.get("option_greeks") or {}, "observed_ts": observed_ts}))
        return events
