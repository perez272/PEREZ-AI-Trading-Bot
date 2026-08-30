"""Five-second observation cadence without five-second REST hammering."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ObservationSnapshot:
    data: Any
    observed_at: float
    refreshed_at: float
    source: str


@dataclass
class SafeObservationEngine:
    """Coordinate a fast observation loop with slow, budgeted provider reads."""

    cadence_seconds: float = 5.0
    refresh_interval_seconds: float = 300.0
    max_snapshot_age_seconds: float = 390.0
    _snapshots: dict[str, ObservationSnapshot] = field(default_factory=dict)
    _next_refresh: dict[str, float] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=lambda: {
        "observations": 0, "cache_hits": 0, "refresh_due": 0,
        "refresh_successes": 0, "refresh_failures": 0,
        "expired_snapshots": 0, "refresh_deferred": 0,
    })

    def observe(self, key: str, loader: Callable[[], tuple[Any, str]],
                validator: Callable[[Any], bool], now: float | None = None,
                allow_refresh: bool = True) -> ObservationSnapshot | None:
        """Return the latest validated snapshot without blocking the cadence."""
        now = time.monotonic() if now is None else float(now)
        self.stats["observations"] += 1
        snapshot = self._snapshots.get(key)
        due_at = self._next_refresh.get(key, 0.0)

        if snapshot is not None and now < due_at:
            if now - snapshot.refreshed_at <= self.max_snapshot_age_seconds:
                self.stats["cache_hits"] += 1
                return ObservationSnapshot(snapshot.data, now, snapshot.refreshed_at, snapshot.source)

        if not allow_refresh:
            self.stats["refresh_deferred"] += 1
            return self._fallback(key, now)

        self.stats["refresh_due"] += 1
        try:
            data, source = loader()
        except Exception as exc:
            self.stats["refresh_failures"] += 1
            print(f"[OBSERVATION] refresh failed for {key}: {exc}")
            return self._fallback(key, now)

        if validator(data):
            refreshed = ObservationSnapshot(data, now, now, str(source or "unknown"))
            self._snapshots[key] = refreshed
            self._next_refresh[key] = now + self.refresh_interval_seconds
            self.stats["refresh_successes"] += 1
            return refreshed

        self.stats["refresh_failures"] += 1
        print(f"[OBSERVATION] invalid provider payload for {key} — retaining last valid snapshot")
        self._next_refresh[key] = now + min(self.refresh_interval_seconds, self.cadence_seconds * 2)
        return self._fallback(key, now)

    def _fallback(self, key: str, now: float) -> ObservationSnapshot | None:
        snapshot = self._snapshots.get(key)
        if snapshot is None:
            return None
        if now - snapshot.refreshed_at > self.max_snapshot_age_seconds:
            self.stats["expired_snapshots"] += 1
            self._snapshots.pop(key, None)
            return None
        self.stats["cache_hits"] += 1
        return ObservationSnapshot(snapshot.data, now, snapshot.refreshed_at, snapshot.source)

    def seconds_until_refresh(self, key: str, now: float | None = None) -> float:
        now = time.monotonic() if now is None else float(now)
        return max(0.0, self._next_refresh.get(key, 0.0) - now)

    def sleep_to_next_observation(self, started_at: float) -> None:
        remaining = self.cadence_seconds - (time.monotonic() - started_at)
        if remaining > 0:
            time.sleep(remaining)
