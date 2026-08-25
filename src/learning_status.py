"""Read-only runtime/learning telemetry for Telegram and diagnostics.

This module never changes trading decisions. It only reports persisted evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.risk_manager import daily_summary
from src.tier1_option_observer import get_tier1_option_observer

STATUS_PATH = Path("data/runtime/learning_status.json")


def _load() -> dict[str, Any]:
    try:
        if STATUS_PATH.exists():
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    return {"rejections": 0, "lessons_events": 0, "last_observation": None, "last_events": []}


def record_cycle(*, observations: int = 0, rejections: int = 0, lessons_events: int = 0, events: list[dict[str, Any]] | None = None) -> None:
    data = _load()
    data["rejections"] = int(data.get("rejections", 0)) + max(0, int(rejections))
    data["lessons_events"] = int(data.get("lessons_events", 0)) + max(0, int(lessons_events))
    if observations:
        from datetime import datetime, timezone
        data["last_observation"] = datetime.now(timezone.utc).isoformat()
    if events:
        data["last_events"] = events[-10:]
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def get_learning_status() -> dict[str, Any]:
    observer = get_tier1_option_observer()
    observer_stats = observer.stats()
    data = _load()
    risk = daily_summary()
    return {
        "completed_paper_trades": risk["closed_trades"],
        "wins": observer_stats.get("wins", 0),
        "learned_win_rate": observer_stats.get("win_rate", 0.0),
        "learned_pnl": risk["pnl"],
        "observations": observer_stats.get("observations", 0),
        "rejections": int(data.get("rejections", 0)),
        "lessons_events": int(data.get("lessons_events", 0)),
        "option_surge_events": observer_stats.get("surge_events", 0),
        "outcome_learning": "READY" if risk["closed_trades"] else "WAITING_FOR_FIRST_CLOSED_TRADE",
        "pattern_learning": "READY" if observer_stats.get("observations", 0) else "WAITING_FOR_OBSERVATIONS",
        "last_observation": data.get("last_observation"),
        "last_events": data.get("last_events", []),
    }
