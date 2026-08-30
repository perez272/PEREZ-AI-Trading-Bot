"""Fail-closed sensors for market-data pipeline integrity.

Sensors consume data already produced by the bot. They never make API calls,
fabricate prices, or bypass the existing market-data/risk path.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class PipelineSensor:
    max_age_seconds: float = 390.0
    expected_interval_seconds: float = 60.0
    last_stage: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def record(self, stage: str, *, timestamp: datetime | None = None,
               rows: int | None = None, source: str | None = None,
               valid: bool = True, error: str | None = None) -> dict[str, Any]:
        now = timestamp or datetime.now(timezone.utc)
        item = {"stage": stage, "timestamp": now.isoformat(), "rows": rows,
                "source": source, "valid": bool(valid), "error": error}
        self.last_stage[stage] = item
        if not valid or (rows is not None and rows <= 0):
            self.failures.append(f"{stage}: invalid_or_empty")
        if error:
            self.failures.append(f"{stage}: {error}")
        return item

    def check_freshness(self, observed_at: datetime, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        age = (current - observed_at).total_seconds()
        healthy = -60.0 <= age <= self.max_age_seconds
        if not healthy:
            self.failures.append(f"freshness: age={age:.1f}s")
        return {"healthy": healthy, "age_seconds": round(age, 2), "max_age_seconds": self.max_age_seconds}

    def check_continuity(self, previous_at: datetime, current_at: datetime) -> dict[str, Any]:
        if previous_at.tzinfo is None:
            previous_at = previous_at.replace(tzinfo=timezone.utc)
        if current_at.tzinfo is None:
            current_at = current_at.replace(tzinfo=timezone.utc)
        gap = (current_at - previous_at).total_seconds()
        healthy = 0 <= gap <= self.expected_interval_seconds * 2.5
        if not healthy:
            self.failures.append(f"continuity: gap={gap:.1f}s")
        return {"healthy": healthy, "gap_seconds": round(gap, 2), "expected_interval_seconds": self.expected_interval_seconds}

    def snapshot(self) -> dict[str, Any]:
        return {"healthy": not self.failures, "last_stage": dict(self.last_stage), "failure_count": len(self.failures), "failures": list(self.failures[-20:])}
